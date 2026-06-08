#############
#  imports  #
#############

########################
#  STATE DECLARATIONS  #
########################

# flask socketio reference — set once on startup
_flask_socketio = None
_flask_app = None
_bot_event_loop = None

####################
#  GLOBAL METHODS  #
####################
def set_bot_event_loop(loop):
    global _bot_event_loop
    _bot_event_loop = loop

def get_bot_event_loop():
    return _bot_event_loop


def set_socketio(flask_socketio, flask_app):
    global _flask_socketio, _flask_app
    _flask_socketio = flask_socketio
    _flask_app = flask_app


def emit_ui_update(event_type: str, data: dict):
    if _flask_socketio and _flask_app:
        with _flask_app.app_context():
            _flask_socketio.emit("batch_update", [{"event_type": event_type, "data": data}])
    else:
        print(f"[emit_ui_update] socketio not set — dropping {event_type}")