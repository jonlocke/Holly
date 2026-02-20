from flask import Flask, render_template, request, Response
from ollama import Client
import os

app = Flask(__name__)

client = Client(
    host=os.environ.get("OLLAMA_API_BASE", "http://localhost:11434")
)

MODEL = "gpt-oss:120b-cloud"

@app.route("/")
def index():
    return render_template("index.html")


def format_sse(data: str) -> str:
    """
    Properly format text for Server-Sent Events.
    Handles CR/LF normalization and multi-line content.
    """
    # Normalize all CRLF / CR to LF
    data = data.replace("\r\n", "\n").replace("\r", "\n")

    # Split into lines and prefix each with 'data: '
    lines = data.split("\n")
    return "".join(f"data: {line}\n" for line in lines) + "\n"


@app.route("/stream")
def stream():
    user_message = request.args.get("message")

    def generate():
        try:
            stream = client.chat(
                model=MODEL,
                messages=[{"role": "user", "content": user_message}],
                stream=True
            )

            for chunk in stream:
                if "message" in chunk:
                    content = chunk["message"].get("content", "")
                    if content:
                        yield format_sse(content)

        except Exception as e:
            yield format_sse(f"ERROR: {str(e)}")

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # prevents buffering in nginx
        },
    )


if __name__ == "__main__":
    debug = os.getenv("FLASK_DEBUG", "0") == "1"
    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "5000"))
    app.run(debug=debug, threaded=True, host=host, port=port)
