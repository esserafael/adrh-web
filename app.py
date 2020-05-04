from _version import __version__
import os
import base64
import uuid
import requests
from flask import Flask, render_template, session, request, redirect, url_for, flash
from werkzeug.utils import secure_filename
from flask_session import Session  # https://pythonhosted.org/Flask-Session
import msal
import app_config


app = Flask(__name__)
app.config.from_object(app_config)
Session(app)

def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in app_config.ALLOWED_EXTENSIONS

def get_graph_data(endpoint):
    token = _get_token_from_cache(app_config.SCOPE)
    if not token:
        return redirect(url_for("login"))
    graph_data = requests.get(  # Use token to call downstream service
        endpoint,
        headers={'Authorization': 'Bearer ' + token['access_token']},
        )
    return graph_data


@app.route("/")
def index():
    if not session.get("user"):
        return redirect(url_for("login"))
    return render_template(
        app_config.PAGE_WRAPPER,
        content="index.html",
        user=session["user"],
        user_basic_data=session["me_data"],
        version=__version__
        )

@app.route("/login")
def login():
    session["state"] = str(uuid.uuid4())
    # Technically we could use empty list [] as scopes to do just sign in,
    # here we choose to also collect end user consent upfront
    auth_url = _build_auth_url(scopes=app_config.SCOPE, state=session["state"])
    return render_template(
        "login.html",
        auth_url=auth_url,
        version=__version__
        )

@app.route(app_config.REDIRECT_PATH)  # Its absolute URL must match your app's redirect_uri set in AAD
def authorized():
    #print("Request State: {}".format(request.args.get('state')))
    #print("Session: {}".format(session))
    if request.args.get('state') != session.get("state"):
        return redirect(url_for("index"))  # No-OP. Goes back to Index page
    if "error" in request.args:  # Authentication/Authorization failure
        return render_template("autherror.html", result=request.args)
    if request.args.get('code'):
        cache = _load_cache()
        #print("Request Code: {}".format(request.args.get('code')))
        #print("Cache: {}".format(cache))
        result = _build_msal_app(cache=cache).acquire_token_by_authorization_code(
            request.args['code'],
            scopes=app_config.SCOPE,  # Misspelled scope would cause an HTTP 400 error here
            redirect_uri=url_for("authorized", _external=True))
            #redirect_uri=url_for("authorized", _external=True, _scheme="https"))
        if "error" in result:
            return render_template("autherror.html", result=result)
        #print("Result: {}".format(result))
        session["user"] = result.get("id_token_claims")
        print("Session 2: {}".format(session["user"]))
        _save_cache(cache)
    me_data = get_graph_data("https://graph.microsoft.com/v1.0/me/").json()
    me_data["me_pic"] = (base64.b64encode(get_graph_data("https://graph.microsoft.com/v1.0/me/photo/$value")._content)).decode()
    session["me_data"] = me_data
    return redirect(url_for("index"))

@app.route("/logout")
def logout():
    session.clear()  # Wipe out user and its token cache from session
    return redirect(  # Also logout from your tenant's web session
        app_config.AUTHORITY + "/oauth2/v2.0/logout" +
        "?post_logout_redirect_uri=" + url_for("index", _external=True))

@app.route("/create")
def create():
    token = _get_token_from_cache(app_config.SCOPE)
    if not token:
        return redirect(url_for("login"))
    return render_template(
        app_config.PAGE_WRAPPER,
        content="create.html",
        user_basic_data=session["me_data"],
        version=__version__
        )

@app.route("/create/save")
def create_save():
    token = _get_token_from_cache(app_config.SCOPE)
    if not token:
        return redirect(url_for("login"))
    if True:
        return render_template(
            'save.html',
            result="Conta criada com sucesso!",
            user_basic_data=session["me_data"],
            version=__version__
            )

@app.route("/upload", methods=['GET', 'POST'])
def upload():
    token = _get_token_from_cache(app_config.SCOPE)
    if not token:
        return redirect(url_for("login"))
    if request.method == 'POST':
        # check if the post request has the file part
        if 'file' not in request.files:
            flash('Sem arquivo na solicitação de envio.')
            return redirect(request.url)
        file = request.files['file']
        # if user does not select file, browser also
        # submit an empty part without filename
        if file.filename == '':
            flash('Nenhum arquivo selecionado, por favor tente novamente.')
            return redirect(request.url)
        if not allowed_file(file.filename):
            flash('Somente arquivos Excel (.xlsx) ou Separados por vírgulas (.csv) podem ser enviados.')
            return redirect(request.url)
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            filename_withid = "{}__email__{}.{}".format(filename.rsplit('.', 1)[0].lower(), session["user"].get("preferred_username"), filename.rsplit('.', 1)[1].lower())
            file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename_withid))
            return render_template(
                app_config.PAGE_WRAPPER,
                content="save.html",
                result="Arquivo {} enviado com sucesso!".format(filename),
                filename=filename, 
                user_basic_data=session["me_data"],
                version=__version__
                )
    return render_template(
        app_config.PAGE_WRAPPER,
        content="upload.html",
        user_basic_data=session["me_data"],
        version=__version__)


@app.route("/graphcall")
def graphcall():
    token = _get_token_from_cache(app_config.SCOPE)
    if not token:
        return redirect(url_for("login"))
    graph_data = get_graph_data("https://graph.microsoft.com/v1.0/me/").json()
    return render_template('display.html', result=graph_data)

def _load_cache():
    cache = msal.SerializableTokenCache()
    if session.get("token_cache"):
        cache.deserialize(session["token_cache"])
    return cache

def _save_cache(cache):
    if cache.has_state_changed:
        session["token_cache"] = cache.serialize()

def _build_msal_app(cache=None, authority=None):
    return msal.ConfidentialClientApplication(
        app_config.CLIENT_ID, authority=authority or app_config.AUTHORITY,
        client_credential=app_config.CLIENT_SECRET, token_cache=cache)

def _build_auth_url(authority=None, scopes=None, state=None):
    return _build_msal_app(authority=authority).get_authorization_request_url(
        scopes or [],
        state=state or str(uuid.uuid4()),
        redirect_uri=url_for("authorized", _external=True))
        #redirect_uri=url_for("authorized", _external=True, _scheme="https"))

def _get_token_from_cache(scope=None):
    cache = _load_cache()  # This web app maintains one cache per session
    cca = _build_msal_app(cache=cache)
    accounts = cca.get_accounts()
    if accounts:  # So all account(s) belong to the current signed-in user
        result = cca.acquire_token_silent(scope, account=accounts[0])
        _save_cache(cache)
        return result

app.jinja_env.globals.update(_build_auth_url=_build_auth_url)  # Used in template

if __name__ == "__main__":
    app.run()

