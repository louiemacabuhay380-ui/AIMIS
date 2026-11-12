"""Routes for AIMIS Coach, the chatbot that answers questions about the student's own interviews."""
import json
import time

from flask import request, session, jsonify, Response, stream_with_context, url_for

import rag
import account_actions

MAX_QUESTION_CHARS = 500
HISTORY_SHOWN = 30


def register(app, get_db, load_report):

    def current_user():
        return session.get("user_id")

    def own_interview(cursor, user_id, interview_id):
        """The interview id if it belongs to this student, else None."""
        if not interview_id:
            return None
        try:
            interview_id = int(interview_id)
        except (TypeError, ValueError):
            return None
        cursor.execute("SELECT interview_id FROM interviews WHERE interview_id = %s AND user_id = %s",
                       (interview_id, user_id))
        return interview_id if cursor.fetchone() else None

    def scope_sql(interview_id):
        return ("interview_id = %s", interview_id) if interview_id else ("interview_id IS NULL", None)

    def chat_history():
        user_id = current_user()
        if not user_id:
            return jsonify(error="login"), 401
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        interview_id = own_interview(cursor, user_id, request.args.get("interview_id"))
        where, value = scope_sql(interview_id)
        params = [user_id] + ([value] if value else []) + [HISTORY_SHOWN]
        try:
            cursor.execute(f"""SELECT role, content, sources FROM chat_messages
                               WHERE user_id = %s AND {where}
                               ORDER BY message_id DESC LIMIT %s""", params)
            rows = list(reversed(cursor.fetchall()))
        except Exception as e:
            conn.close()
            if getattr(e, "errno", None) == 1146:
                return jsonify(messages=[], setup="Run block 7 of database/schema_updates.sql first.")
            raise
        conn.close()
        return jsonify(messages=[{"role": r["role"], "content": r["content"],
                                  "sources": json.loads(r["sources"]) if r["sources"] else []} for r in rows])

    def chat_clear():
        user_id = current_user()
        if not user_id:
            return jsonify(error="login"), 401
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        interview_id = own_interview(cursor, user_id, (request.get_json(silent=True) or {}).get("interview_id"))
        where, value = scope_sql(interview_id)
        cursor.execute(f"DELETE FROM chat_messages WHERE user_id = %s AND {where}",
                       [user_id] + ([value] if value else []))
        conn.commit()
        conn.close()
        return jsonify(ok=True)

    def chat_status():
        if not current_user():
            return jsonify(error="login"), 401
        status = rag.ollama_status()
        if status.get("running") and status.get("has_chat_model"):
            rag.warm_up()          # start loading the model now, while the student types
        return jsonify(status)

    def chat_ask():
        user_id = current_user()
        if not user_id:
            return jsonify(error="Please log in again."), 401
        data = request.get_json(silent=True) or {}
        question = " ".join(str(data.get("message") or "").split())[:MAX_QUESTION_CHARS]
        if not question:
            return jsonify(error="Type a question first."), 400

        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        interview_id = own_interview(cursor, user_id, data.get("interview_id"))

        # Account request ("change my name to ..."): handled by fixed rules, never by the AI. A change is only
        # proposed here; it is saved after the student presses Confirm (chat_action below).
        action = account_actions.detect(question)
        if action:
            cursor.execute("SELECT full_name, career_goal FROM users WHERE user_id = %s", (user_id,))
            user = cursor.fetchone()
            urls = {"career": url_for("career_goal"), "forgot": url_for("forgot_password"), "my_data": url_for("my_data")}
            answer = account_actions.reply_for(action, user, urls)
            payload = {"type": "account", "text": answer["text"]}
            if answer.get("confirm"):
                payload["action_id"] = account_actions.remember(session, action)
            if answer.get("link"):
                payload["link"] = {"label": answer["link"][0], "url": answer["link"][1]}
            save_exchange(cursor, user_id, interview_id, question, answer["text"])
            conn.commit()
            conn.close()
            return jsonify(payload)

        # Off-topic question ("What food should I eat?"): polite fixed reply, no data looked up or sent to the AI
        refusal = rag.off_topic_reply(question)
        if refusal:
            cursor.execute("INSERT INTO chat_messages (user_id, interview_id, role, content) VALUES (%s, %s, 'user', %s)",
                           (user_id, interview_id, question))
            cursor.execute("""INSERT INTO chat_messages (user_id, interview_id, role, content, sources)
                              VALUES (%s, %s, 'bot', %s, '[]')""", (user_id, interview_id, refusal))
            conn.commit()
            conn.close()
            response = Response(refusal, mimetype="text/plain; charset=utf-8")
            response.headers["X-Chat-Sources"] = "[]"
            return response

        try:
            rag.ensure_indexed(conn, user_id, load_report)     # 1. index anything new
        except Exception as e:
            conn.close()
            if getattr(e, "errno", None) == 1146:
                return jsonify(error="The chatbot tables are missing. Run block 7 of database/schema_updates.sql."), 500
            raise
        started = time.perf_counter()
        context, sources, method = rag.build_context(cursor, user_id, question, interview_id)   # 2. retrieve
        print(f"Chatbot search ({method}) took {time.perf_counter() - started:.1f}s, "
              f"about {len(context) // 4} tokens of data")

        where, value = scope_sql(interview_id)
        cursor.execute(f"""SELECT role, content FROM chat_messages WHERE user_id = %s AND {where}
                           ORDER BY message_id DESC LIMIT 4""", [user_id] + ([value] if value else []))
        history = list(reversed(cursor.fetchall()))
        cursor.execute("INSERT INTO chat_messages (user_id, interview_id, role, content) VALUES (%s, %s, 'user', %s)",
                       (user_id, interview_id, question))
        conn.commit()
        conn.close()

        def generate():                                         # 3. generate (streamed)
            reply = []
            try:
                for piece in rag.stream_answer(context, history, question):
                    reply.append(piece)
                    yield piece
            except Exception as e:
                print("Chatbot failed:", e)
                msg = "Sorry, something went wrong while answering. Please try again."
                reply.append(msg)
                yield msg
            finally:
                text = "".join(reply).strip()
                if text:
                    save = get_db()
                    c = save.cursor()
                    c.execute("""INSERT INTO chat_messages (user_id, interview_id, role, content, sources)
                                 VALUES (%s, %s, 'bot', %s, %s)""",
                              (user_id, interview_id, text, json.dumps(sources)))
                    save.commit()
                    save.close()

        response = Response(stream_with_context(generate()), mimetype="text/plain; charset=utf-8")
        response.headers["X-Chat-Sources"] = json.dumps(sources)     # shown as links under the reply
        response.headers["X-Chat-Search"] = method
        response.headers["Cache-Control"] = "no-cache"
        return response

    def save_exchange(cursor, user_id, interview_id, question, reply):
        if question:
            cursor.execute("INSERT INTO chat_messages (user_id, interview_id, role, content) VALUES (%s, %s, 'user', %s)",
                           (user_id, interview_id, question))
        cursor.execute("""INSERT INTO chat_messages (user_id, interview_id, role, content, sources)
                          VALUES (%s, %s, 'bot', %s, '[]')""", (user_id, interview_id, reply))

    def chat_action():
        """The student pressed Confirm or Cancel on a change the chatbot proposed."""
        user_id = current_user()
        if not user_id:
            return jsonify(error="Please log in again."), 401
        data = request.get_json(silent=True) or {}
        pending = account_actions.take(session, str(data.get("action_id") or ""))
        if not pending:
            return jsonify(ok=False, text="That request has expired. Type it again and I'll ask you to confirm.")
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        interview_id = own_interview(cursor, user_id, data.get("interview_id"))
        if data.get("decision") != "confirm":
            text = "Okay, I didn't change anything."
        elif pending["kind"] == "name":
            cursor.execute("UPDATE users SET full_name = %s WHERE user_id = %s", (pending["value"], user_id))
            session["full_name"] = pending["value"]
            text = f"Done. Your name is now **{pending['value']}**."
        elif pending["kind"] == "career":
            cursor.execute("UPDATE users SET career_goal = %s WHERE user_id = %s", (pending["value"], user_id))
            text = f"Done. Your career goal is now **{pending['value']}**. Your next interview will be set in this job."
        else:
            text = "Sorry, I can't do that here."
        save_exchange(cursor, user_id, interview_id, None, text)
        conn.commit()
        conn.close()
        return jsonify(ok=True, text=text, changed=data.get("decision") == "confirm", kind=pending["kind"],
                       value=pending["value"])

    app.add_url_rule("/chat/action", "chat_action", chat_action, methods=["POST"])
    app.add_url_rule("/chat/history", "chat_history", chat_history)
    app.add_url_rule("/chat/clear", "chat_clear", chat_clear, methods=["POST"])
    app.add_url_rule("/chat/status", "chat_status", chat_status)
    app.add_url_rule("/chat/ask", "chat_ask", chat_ask, methods=["POST"])
