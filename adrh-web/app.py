from _version import __version__
import os
from datetime import datetime
import base64
import uuid
import re
import requests
from ast import literal_eval
import json
#from flask import Flask, render_template, session, request, redirect, url_for, flash
from quart import Quart, render_template, session, request, redirect, url_for, flash
from werkzeug.utils import secure_filename
from quart_session import Session  # https://pythonhosted.org/Flask-Session
import msal
import app_config


app = Quart(__name__)
app.config.from_object(app_config)
Session(app)


@app.route("/")
async def index():
    session = app.session_interface
    if not await session.get("user"):
        return redirect(url_for("login"))
    me_data = await session.get("me_data")
    return await _render_custom_template("index.html", me_data)

@app.route("/login")
async def login():
    session = app.session_interface
    await session.set("state", str(uuid.uuid4()), app_config.SESSION_TIMEOUT)
    #session["state"] = str(uuid.uuid4())
    print((await session.get("state")).decode())
    # Technically we could use empty list [] as scopes to do just sign in,
    # here we choose to also collect end user consent upfront
    auth_url = (await _build_auth_url(scopes=app_config.SCOPE, state=await session.get("state")))
    return await render_template(
        "login.html",
        auth_url=auth_url,
        version=__version__
        )

@app.route(app_config.REDIRECT_PATH)  # Its absolute URL must match your app's redirect_uri set in AAD
async def authorized():
    session = app.session_interface
    #print("Request State: {}".format(request.args.get("state").encode()))
    #print("Session State: {}".format(str(await session.get("state"))))
    if request.args.get("state").encode() != (await session.get("state")):
        return redirect(url_for("index"))  # No-OP. Goes back to Index page
    if "error" in request.args:  # Authentication/Authorization failure
        print(request.args)
        return await render_template("autherror.html", result=request.args)
    if request.args.get('code'):
        cache = await _load_cache()
        result = (await _build_msal_app(cache=cache)).acquire_token_by_authorization_code(
            request.args['code'],
            scopes=app_config.SCOPE,  # Misspelled scope would cause an HTTP 400 error here
            redirect_uri=url_for("authorized", _external=True))
            #redirect_uri=url_for("authorized", _external=True, _scheme="https"))
        if "error" in result:
            print(result)
            return await render_template("autherror.html", result=result)
        await session.set("user", result.get("id_token_claims"), app_config.SESSION_TIMEOUT)
        await _save_cache(cache)
        me_data = (await _get_graph_data("https://graph.microsoft.com/v1.0/me/")).json()
        #me_data = me_data.json()
        #me_data["me_pic"] = (await _get_graph_data("https://graph.microsoft.com/v1.0/me/photo/$value"))
        me_data["me_pic"] = (base64.b64encode((await _get_graph_data("https://graph.microsoft.com/v1.0/me/photo/$value"))._content)).decode()
        await session.set("me_data", me_data, app_config.SESSION_TIMEOUT)
    return redirect(url_for("index"))

@app.route("/logout")
async def logout():
    session = app.session_interface
    await session.delete("user")
    await session.delete("token_cache")
    #session.clear()  # Wipe out user and its token cache from session
    return redirect(  # Also logout from your tenant's web session
        app_config.AUTHORITY + "/oauth2/v2.0/logout" +
        "?post_logout_redirect_uri=" + url_for("index", _external=True))

@app.route("/create", methods=['GET', 'POST'])
async def create():
    session = app.session_interface
    if not await session.get("user"):
        return redirect(url_for("login"))
    me_data = await session.get("me_data")
    if request.method == 'POST':
        form_data = await request.form
        print(form_data["surname"])
        switcher={
            "gn": "Nome",
            "surname": "Sobrenome",
            "cpf": "CPF",
            "email": "E-mail",
            "department": "Departamento",
            "gestor": "Gestor",
            "perm": "Permissão",
            "cel": "Celular",
            "altemail": "E-mail alternativo"
        }
        return await _render_custom_template("save.html", me_data, result="Conta criada com sucesso!", new_user_data=form_data, switcher=switcher)
    return await _render_custom_template("create.html", me_data)

@app.route("/create/save", methods=['GET', 'POST'])
async def create_save():
    session = app.session_interface
    if not await session.get("user"):
        return redirect(url_for("login"))
    me_data = await session.get("me_data")
    return await _render_custom_template("save.html", me_data, result="Conta criada com sucesso!")

@app.route("/upload", methods=['GET', 'POST'])
async def upload():

    async def _allowed_file(filename):
        return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in app_config.ALLOWED_EXTENSIONS

    session = app.session_interface
    if not await session.get("user"):
        return redirect(url_for("login"))
    me_data = await session.get("me_data")
    if request.method == 'POST':
        # check if the post request has the file part
        if 'file' not in  await request.files:
            await flash('Sem arquivo na solicitação de envio.')
            return redirect(request.url)
        file = (await request.files)['file']
        # if user does not select file, browser also
        # submit an empty part without filename
        if file.filename == '':
            await flash('Nenhum arquivo selecionado, por favor tente novamente.')
            return redirect(request.url)
        if not await _allowed_file(file.filename):
            await flash('Somente arquivos Excel (.xlsx) ou Separados por vírgulas (.csv) podem ser enviados.')
            return redirect(request.url)
        if file and await _allowed_file(file.filename):
            filename = secure_filename(file.filename)
            filename_withid = "{}_{}.{}".format(
                uuid.uuid4().hex,
                (literal_eval(me_data.decode('utf8')))['mail'],
                filename.rsplit('.', 1)[1].lower()
                )
            file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename_withid))
            return await _render_custom_template(
                "save.html",
                me_data,
                result="Arquivo '{}' enviado com sucesso!".format(filename),
                filename=filename
                )
    return await _render_custom_template("upload.html", me_data)


@app.route("/graphcall")
def graphcall():
    token = _get_token_from_cache(app_config.SCOPE)
    if not token:
        return redirect(url_for("login"))
    graph_data = get_graph_data("https://graph.microsoft.com/v1.0/me/").json()
    return render_template('display.html', result=graph_data)

@app.errorhandler(404)
async def page_not_found(e):
    # note that we set the 404 status explicitly
    return await render_template('404.html'), 404

async def _build_auth_url(authority=None, scopes=None, state=None):
    return (await _build_msal_app(authority=authority)).get_authorization_request_url(
        scopes or [],
        state=state or str(uuid.uuid4()),
        redirect_uri=url_for("authorized", _external=True))
        #redirect_uri=url_for("authorized", _external=True, _scheme="https"))

async def _load_cache():
    session = app.session_interface
    cache = msal.SerializableTokenCache()
    if await session.get("token_cache"):
        cache.deserialize((await session.get("token_cache")).decode())
    return cache

async def _save_cache(cache):
    session = app.session_interface
    if cache.has_state_changed:
        await session.set("token_cache", cache.serialize(), app_config.SESSION_TIMEOUT)

async def _build_msal_app(cache=None, authority=None):
    return msal.ConfidentialClientApplication(
        app_config.CLIENT_ID, authority=authority or app_config.AUTHORITY,
        client_credential=app_config.CLIENT_SECRET, token_cache=cache)

async def _get_token_from_cache(scope=None):
    cache = await _load_cache()  # This web app maintains one cache per session
    cca = await _build_msal_app(cache=cache)
    accounts = cca.get_accounts()
    if accounts:  # So all account(s) belong to the current signed-in user
        result = cca.acquire_token_silent(scope, account=accounts[0])
        await _save_cache(cache)
        return result

async def _get_graph_data(endpoint):
    token = await _get_token_from_cache(app_config.SCOPE)
    if not token:
        return redirect(url_for("login"))
    graph_data = requests.get(  # Use token to call downstream service
        endpoint,
        headers={'Authorization': 'Bearer ' + token['access_token']},
        )
    return graph_data

async def _render_custom_template(file, user_basic_data, **context):
    print(context)
    return await render_template(
        app_config.PAGE_WRAPPER,
        content=file,
        user_basic_data=literal_eval(user_basic_data.decode('utf8')),
        version=__version__,
        **context
        ) 

app.jinja_env.globals.update(_build_auth_url=_build_auth_url)  # Used in template

if __name__ == "__main__":
    app.run()

