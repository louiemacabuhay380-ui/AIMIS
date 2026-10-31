"""Routes for AIMIS Coach, the chatbot that answers questions about the student's own interviews."""
import json

from flask import request, session, jsonify, Response, stream_with_context

import rag

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
        return jsonify(rag.ollama_status())

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
        try:
            rag.ensure_indexed(conn, user_id, load_report)     # 1. index anything new
        except Exception as e:
            conn.close()
            if getattr(e, "errno", None) == 1146:
                return jsonify(error="The chatbot tables are missing. Run block 7 of database/schema_updates.sql."), 500
            raise
        context, sources, method = rag.build_context(cursor, user_id, question, interview_id)   # 2. retrieve

        where, value = scope_sql(interview_id)
        cursor.execute(f"""SELECT role, content FROM chat_messages WHERE user_id = %s AND {where}
                           ORDER BY message_id DESC LIMIT 6""", [user_id] + ([value] if value else []))
        history = list(reversed(cursor.fetchall()))
        cursor.execute("INSERT INTO chat_messages (user_id, interview_id, role, content) VALUES (%s, %s, 'user', %s)",
                       (user_id, interview_id, question))
        conn.commit()
        conn.close()
        print(f"Chatbot search: {method}, {len(sources)} sources")

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

    app.add_url_rule("/chat/history", "chat_history", chat_history)
    app.add_url_rule("/chat/clear", "chat_clear", chat_clear, methods=["POST"])
    app.add_url_rule("/chat/status", "chat_status", chat_status)
    app.add_url_rule("/chat/ask", "chat_ask", chat_ask, methods=["POST"])
