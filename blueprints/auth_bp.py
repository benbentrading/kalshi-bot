from flask import Blueprint, redirect, url_for
from flask_login import login_user, logout_user, login_required
import os
from core.classes.user import User

auth_bp = Blueprint('auth', __name__)

ALLOWED_EMAIL = os.getenv('ALLOWED_EMAIL')

@auth_bp.route('/login')
def login():
    from app import oauth
    redirect_uri = os.getenv('OAUTH_REDIRECT_URI')
    return oauth.google.authorize_redirect(redirect_uri)

@auth_bp.route('/auth/callback')
def callback():
    from app import oauth
    token = oauth.google.authorize_access_token()
    email = token['userinfo']['email']

    if email != ALLOWED_EMAIL:
        return "unauthorized", 403

    login_user(User(email), remember=True)
    return redirect('/')

@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('auth.login'))