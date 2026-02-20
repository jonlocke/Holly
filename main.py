from flask import Flask, render_template, request, Response
from ollama import Client
import os
import json

app = Flask(__name__)

client = Client(
    host=os.environ.get("OLLAMA_API_BASE", "http://192.168.1.154:11434")
)

#MODEL = "gpt-oss:120b-cloud"
MODEL = "qwen3:4b-16k"

@app.route("/")
def index():
    return render_template("index.html")


def sse(data: dict) -> str:
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


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
                        yield sse({
                            "type": "token",
                            "content": content
                        })

            yield sse({"type": "done"})

        except Exception as e:
            yield sse({
                "type": "error",
                "error": str(e)
            })

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


if __name__ == "__main__":
    app.run(debug=True, threaded=True)

