"""Flask application factory."""
from flask import Flask, jsonify

from config import MAX_UPLOAD_BYTES, STATIC_DIR, load_env
from web.routes import bp


def create_app():
    load_env()
    app = Flask(__name__, static_folder=STATIC_DIR, static_url_path="")
    app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_BYTES
    app.register_blueprint(bp)

    @app.errorhandler(413)
    def too_big(_):
        return jsonify(error="That request is larger than 16 MB."), 413

    return app
