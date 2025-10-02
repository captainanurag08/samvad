
import os
from datetime import datetime
from werkzeug.utils import secure_filename

from flask import Flask, render_template, request, redirect, session, url_for, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_socketio import SocketIO, emit

import eventlet
eventlet.monkey_patch()

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, "static", "uploads")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

app = Flask(__name__)
app.config["SECRET_KEY"] = "supersecret"
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + os.path.join(BASE_DIR, "chat.db")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

db = SQLAlchemy(app)
socketio = SocketIO(app, cors_allowed_origins="*")

SHARED_PASSWORD = "2730622"   # 🔑 shared password

# ---------- Database ----------
class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50))
    relation = db.Column(db.String(50))
    content = db.Column(db.Text)
    type = db.Column(db.String(20), default="text")  # text or image
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "username": self.username,
            "relation": self.relation,
            "content": self.content,
            "type": self.type,
            "timestamp": self.timestamp.strftime("%H:%M")
        }

with app.app_context():
    db.create_all()

# ---------- Routes ----------
@app.route("/", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        username = request.form.get("username") or "Guest"
        relation = request.form.get("relation") or ""
        password = request.form.get("password")

        if password == SHARED_PASSWORD:
            session["username"] = username
            session["relation"] = relation
            return redirect(url_for("chat"))
        else:
            error = "Invalid password"

    return render_template("login.html", error=error)

@app.route("/chat")
def chat():
    if "username" not in session:
        return redirect(url_for("login"))
    messages = [m.to_dict() for m in Message.query.order_by(Message.id).all()]
    return render_template("chat.html",
                           username=session["username"],
                           relation=session["relation"],
                           messages=messages)

@app.route("/upload", methods=["POST"])
def upload_file():
    if "username" not in session:
        return jsonify({"error": "not logged in"}), 401
    file = request.files.get("file")
    if not file:
        return jsonify({"error": "no file"}), 400
    fname = secure_filename(file.filename)
    path = os.path.join(app.config["UPLOAD_FOLDER"], fname)
    file.save(path)
    url = url_for("static", filename=f"uploads/{fname}")
    msg = Message(username=session["username"], relation=session["relation"],
                  content=url, type="image")
    db.session.add(msg)
    db.session.commit()
    socketio.emit("new_message", msg.to_dict(), broadcast=True)
    return jsonify({"ok": True, "url": url})

# ---------- Socket.IO ----------
online_users = {}

@socketio.on("join")
def on_join(data):
    sid = request.sid
    online_users[sid] = {"username": data["username"], "relation": data["relation"]}
    emit("online_list", list(online_users.values()), broadcast=True)

@socketio.on("send_message")
def handle_message(data):
    content = data.get("content", "").strip()
    if not content: return
    msg = Message(username=session.get("username"),
                  relation=session.get("relation"),
                  content=content, type="text")
    db.session.add(msg)
    db.session.commit()
    socketio.emit("new_message", msg.to_dict(), broadcast=True)

@socketio.on("typing")
def handle_typing(_):
    user = session.get("username")
    if user:
        emit("user_typing", {"username": user}, broadcast=True, include_self=False)

@socketio.on("disconnect")
def on_disconnect():
    online_users.pop(request.sid, None)
    emit("online_list", list(online_users.values()), broadcast=True)

# ---------- Run ----------
if __name__ == "__main__":
    port=int(os.environ.get("PORT",5000))
    app.run(host="0.0.0.0",port=port)