####################
#       app.py     #
#  flask app init  #
####################

from flask import Flask
from flask_socketio import SocketIO
import threading
import asyncio
import os
import logging
import logging
from core.bot_init import start_bot
from flask_login import LoginManager, UserMixin, current_user
from core.classes.user import User
from authlib.integrations.flask_client import OAuth
from flask import Flask, request, redirect, url_for

# local
from blueprints.main import main_bp
from blueprints.bot_bp import bot_bp
from blueprints.history_bp import history_bp
from blueprints.auth_bp import auth_bp


################
#  GLOBAL VAR  #
################
_bot_thread_started = False
login_manager = LoginManager()
oauth = OAuth()


@login_manager.user_loader
def load_user(email):
    return User(email)


def create_app():
    global _bot_thread_started
    app = Flask(__name__)

    # config
    app.config['SECRET_KEY'] = os.getenv('FLASK_SECRET_KEY')

    # auth/login setup
    login_manager.init_app(app)
    login_manager.login_view = 'auth.login'
    oauth.init_app(app)
    oauth.register(
        name='google',
        client_id=os.getenv('GOOGLE_CLIENT_ID'),
        client_secret=os.getenv('GOOGLE_CLIENT_SECRET'),
        server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
        client_kwargs={'scope': 'openid email'},
    )

    # ====================== CUSTOM FILTERS ======================
    @app.template_filter('format_number')
    def format_number(value, subtract_from=None):
        if value is None:
            return "—"
        try:
            v = float(value)
            if subtract_from is not None:
                v = subtract_from - v
            return f"{v:.2f}"
        except (ValueError, TypeError):
            return "—"
        
    @app.before_request
    def require_login():
        allowed = {'auth.login', 'auth.callback', 'static'}
        if request.endpoint not in allowed and not current_user.is_authenticated:
            return redirect(url_for('auth.login'))

    # socket object
    socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

    # ====================== BOT BACKGROUND THREAD ======================
    def run_async_bot():
        asyncio.run(start_bot(flask_socketio=socketio, flask_app=app))

    if not _bot_thread_started:
        thread = threading.Thread(target=run_async_bot, daemon=True)
        thread.start()
        _bot_thread_started = True

    app.register_blueprint(main_bp)
    app.register_blueprint(bot_bp)
    app.register_blueprint(history_bp)
    app.register_blueprint(auth_bp)

    return app, socketio   # return both


# Create app instance
app, socketio = create_app()

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    debug = os.getenv("FLASK_DEBUG", "False").lower() == "true"
    
    print(f"Starting Flask server → http://127.0.0.1:{port}")
    socketio.run(app, host="0.0.0.0", port=port, debug=debug, use_reloader=False)