import os

from flask import Flask, jsonify


def create_app() -> Flask:
    """Create and configure the Flask application."""

    app = Flask(__name__)

    @app.get("/")
    def home():
        return jsonify(
            {
                "service": "deployment-tracker",
                "status": "running",
            }
        )

    @app.get("/health")
    def health():
        return jsonify(
            {
                "status": "healthy",
            }
        )

    @app.get("/version")
    def version():
        return jsonify(
            {
                "version": os.getenv("APP_VERSION", "dev"),
                "build_number": os.getenv("BUILD_NUMBER", "local"),
                "git_commit": os.getenv("GIT_COMMIT", "unknown"),
            }
        )

    @app.get("/info")
    def info():
        return jsonify(
            {
                "service": "deployment-tracker",
                "status": "running",
                "version": os.getenv("APP_VERSION", "dev"),
                "environment": os.getenv("APP_ENV", "local"),
                "build_number": os.getenv("BUILD_NUMBER", "local"),
                "git_commit": os.getenv("GIT_COMMIT", "unknown"),
            }
        )

    return app


app = create_app()


if __name__ == "__main__":
    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "5000"))
    app.run(host=host, port=port)
