from flask import (Flask,
                   render_template,
                   request,
                   redirect,
                   jsonify,
                   url_for,
                   flash)
from sqlalchemy import create_engine, asc
from sqlalchemy.orm import sessionmaker
from database_setup import Base, Catalog, Item, User
from flask import session as login_session
import random
import string
from oauth2client.client import flow_from_clientsecrets
from oauth2client.client import FlowExchangeError
import httplib2
import json
from flask import make_response
import requests

app = Flask(__name__)

CLIENT_ID = json.loads(
    open('client_secrets.json', 'r').read())['web']['client_id']
APPLICATION_NAME = "Catalog Application"

# create engine
engine = create_engine('sqlite:///itemcatalog.db')
Base.metadata.bind = engine

# create session
DBSession = sessionmaker(bind=engine)
session = DBSession()

# login page to login using facebook or google account


@app.route('/login')
def showLogin():
    state = ''.join(random.choice(string.ascii_uppercase + string.digits)
                    for x in xrange(32))
    login_session['state'] = state
    return render_template('login.html', STATE=state)

# login using facebook


@app.route('/fbconnect', methods=['POST'])
def fbconnect():
    if request.args.get('state') != login_session['state']:
        response = make_response(json.dumps('Invalid state parameter.'), 401)
        response.headers['Content-Type'] = 'application/json'
        return response
    access_token = request.data
    print "access token received %s " % access_token

    app_id = json.loads(open('fb_client_secrets.json', 'r').read())[
        'web']['app_id']
    app_secret = json.loads(open('fb_client_secrets.json', 'r').read())[
        'web']['app_secret']

    url = 'https://graph.facebook.com/oauth/access_token?grant_type=fb_exchange_token&client_id=%s&client_secret=%s&fb_exchange_token=%s' % (app_id, app_secret, access_token)   # NOQA
    h = httplib2.Http()
    result = h.request(url, 'GET')[1]

    userinfo_url = "https://graph.facebook.com/v2.8/me"
    token = result.split(',')[0].split(':')[1].replace('"', '')
    # get user data and add them to login_session
    url = 'https://graph.facebook.com/v2.8/me?access_token=%s&fields=name,id,email' % token   # NOQA
    h = httplib2.Http()
    result = h.request(url, 'GET')[1]
    data = json.loads(result)
    login_session['provider'] = 'facebook'
    login_session['username'] = data['name']
    login_session['email'] = data['email']
    login_session['facebook_id'] = data['id']
    login_session['access_token'] = token
    url = 'https://graph.facebook.com/v2.8/me/picture?access_token=%s&redirect=0&height=200&width=200' % token  # NOQA
    h = httplib2.Http()
    result = h.request(url, 'GET')[1]
    data = json.loads(result)

    login_session['picture'] = data["data"]["url"]
    user_id = getUserID(login_session['email'])
    if not user_id:
        user_id = createUser(login_session)
    login_session['user_id'] = user_id

    output = ''
    output += '<h1>Welcome, '
    output += login_session['username']

    output += '!</h1>'
    output += '<img src="'
    output += login_session['picture']
    output += ' " style = "width: 300px; height: 300px;border-radius:150px;">'

    flash("Now logged in as %s" % login_session['username'])
    return output

# disconnect from facebook. this is used when you logout from the website.
# It's included in logout class.


@app.route('/fbdisconnect')
def fbdisconnect():
    facebook_id = login_session['facebook_id']
    access_token = login_session['access_token']
    url = 'https://graph.facebook.com/%s/permissions?access_token=%s' % (facebook_id, access_token)  # NOQA
    h = httplib2.Http()
    result = h.request(url, 'DELETE')[1]
    return "you have been logged out"

# login using google account


@app.route('/gconnect', methods=['POST'])
def gconnect():
    if request.args.get('state') != login_session['state']:
        response = make_response(json.dumps('Invalid state parameter.'), 401)
        response.headers['Content-Type'] = 'application/json'
        return response
    code = request.data

    try:
        oauth_flow = flow_from_clientsecrets('client_secrets.json', scope='')
        oauth_flow.redirect_uri = 'postmessage'
        credentials = oauth_flow.step2_exchange(code)
    except FlowExchangeError:
        response = make_response(
            json.dumps('Failed to upgrade the authorization code.'), 401)
        response.headers['Content-Type'] = 'application/json'
        return response

    access_token = credentials.access_token
    url = ('https://www.googleapis.com/oauth2/v1/tokeninfo?access_token=%s' % access_token)  # NOQA
    h = httplib2.Http()
    result = json.loads(h.request(url, 'GET')[1])
    if result.get('error') is not None:
        response = make_response(json.dumps(result.get('error')), 500)
        response.headers['Content-Type'] = 'application/json'
        return response

    gplus_id = credentials.id_token['sub']
    if result['user_id'] != gplus_id:
        response = make_response(
            json.dumps("Token's user ID doesn't match given user ID."), 401)
        response.headers['Content-Type'] = 'application/json'
        return response

    if result['issued_to'] != CLIENT_ID:
        response = make_response(
            json.dumps("Token's client ID does not match app's."), 401)
        print "Token's client ID does not match app's."
        response.headers['Content-Type'] = 'application/json'
        return response

    stored_access_token = login_session.get('access_token')
    stored_gplus_id = login_session.get('gplus_id')
    if stored_access_token is not None and gplus_id == stored_gplus_id:
        response = make_response(
            json.dumps('Current user is already connected.'), 200)
        response.headers['Content-Type'] = 'application/json'
        return response

    login_session['access_token'] = credentials.access_token
    login_session['gplus_id'] = gplus_id

    userinfo_url = "https://www.googleapis.com/oauth2/v1/userinfo"  # NOQA
    params = {'access_token': credentials.access_token, 'alt': 'json'}
    answer = requests.get(userinfo_url, params=params)

    data = answer.json()
    # assign user data to login_session
    login_session['username'] = data['name']
    login_session['picture'] = data['picture']
    login_session['email'] = data['email']
    login_session['provider'] = 'google'

    user_id = getUserID(data["email"])
    if not user_id:
        user_id = createUser(login_session)
    login_session['user_id'] = user_id

    output = ''
    output += '<h1>Welcome, '
    output += login_session['username']
    output += '!</h1>'
    output += '<img src="'
    output += login_session['picture']
    output += ' " style = "width:300px;height:300px;border-radius:150px;">'
    flash("you are now logged in as %s" % login_session['username'])
    print "done!"
    return output


# create a new user
def createUser(login_session):
    newUser = User(name=login_session['username'], email=login_session[
                   'email'], picture=login_session['picture'])
    session.add(newUser)
    session.commit()
    user = session.query(User).filter_by(email=login_session['email']).one()
    return user.id

# get information about the user


def getUserInfo(user_id):
    user = session.query(User).filter_by(id=user_id).one()
    return user

# get the user id


def getUserID(email):
    try:
        user = session.query(User).filter_by(email=email).one()
        return user.id
    except BaseException:
        return None

# disconnect from google. this is used to logout of your google account.
# It's included in the logout class


@app.route('/gdisconnect')
def gdisconnect():
    # Only disconnect a connected user.
    access_token = login_session.get('access_token')
    if access_token is None:
        response = make_response(
            json.dumps('Current user not connected.'), 401)
        response.headers['Content-Type'] = 'application/json'
        return response
    url = 'https://accounts.google.com/o/oauth2/revoke?token=%s' % access_token
    h = httplib2.Http()
    result = h.request(url, 'GET')[0]
    if result['status'] == '200':
        response = make_response(json.dumps('Successfully disconnected.'), 200)
        response.headers['Content-Type'] = 'application/json'
        return response
    else:
        response = make_response(
            json.dumps(
                'Failed to revoke token for given user.',
                400))
        response.headers['Content-Type'] = 'application/json'
        return response


# disconnect page to logout using google or facebook
@app.route('/disconnect')
def disconnect():
    if 'provider' in login_session:
        if login_session['provider'] == 'google':
            gdisconnect()
            del login_session['gplus_id']
            del login_session['access_token']
        if login_session['provider'] == 'facebook':
            fbdisconnect()
            del login_session['facebook_id']
        del login_session['username']
        del login_session['email']
        del login_session['picture']
        del login_session['user_id']
        del login_session['provider']
        flash("You have successfully been logged out.")
        return redirect(url_for('showCatalogs'))
    else:
        flash("You were not logged in")
        return redirect(url_for('showCatalogs'))


# show all catalogs in the website.
@app.route('/')
@app.route('/catalog/')
def showCatalogs():
    catalogs = session.query(Catalog).order_by(asc(Catalog.name))
    if 'username' not in login_session:
        return render_template('publicCatalog.html', catalogs=catalogs)
    else:
        return render_template('Catalogs.html', catalogs=catalogs)

# show catalogs information using json.


@app.route('/json')
@app.route('/catalog/json')
def showCatalogsJSON():
    catalogs = session.query(Catalog).order_by(asc(Catalog.name))
    return jsonify(catalogs=[catalog.serialize for catalog in catalogs])


# create a new catalog
@app.route('/catalog/new/', methods=['GET', 'POST'])
def newCatalog():
    if 'username' not in login_session:
        return redirect('/login')
    if request.method == 'POST':
        newCatalog = Catalog(
            name=request.form['name'], user_id=login_session['user_id'])
        session.add(newCatalog)
        session.commit()
        return redirect(url_for('showCatalogs'))
    else:
        return render_template('newCatalog.html')


# edit an existing catalog.
@app.route('/catalog/<int:catalog_id>/edit/', methods=['GET', 'POST'])
def editCatalog(catalog_id):
    editedCatalog = session.query(
        Catalog).filter_by(id=catalog_id).one()
    if 'username' not in login_session:
        return redirect('/login')
    if editedCatalog.user_id != login_session['user_id']:
        return redirect(url_for('showItems', catalog_id=editedCatalog.id))
    if request.method == 'POST':
        if request.form['name']:
            editedCatalog.name = request.form['name']
            return redirect(url_for('showItems', catalog_id=editedCatalog.id))
    else:
        return render_template('editCatalog.html', catalog=editedCatalog)

# delete a catalog.


@app.route('/catalog/<int:catalog_id>/delete/', methods=['GET', 'POST'])
def deleteCatalog(catalog_id):
    catalogToDelete = session.query(
        Catalog).filter_by(id=catalog_id).one()
    if 'username' not in login_session:
        return redirect('/login')
    if catalogToDelete.user_id != login_session['user_id']:
        return redirect(url_for('showCatalogs', catalog_id=catalog_id))
    if request.method == 'POST':
        session.delete(catalogToDelete)
        session.commit()
        return redirect(url_for('showCatalogs', catalog_id=catalog_id))
    else:
        return render_template('deleteCatalog.html', catalog=catalogToDelete)


# show all items inside a catalog
@app.route('/catalog/<int:catalog_id>/')
@app.route('/catalog/<int:catalog_id>/item/')
def showItems(catalog_id):
    catalog = session.query(Catalog).filter_by(id=catalog_id).one()
    creator = getUserInfo(catalog.user_id)
    items = session.query(Item).filter_by(
        catalog_id=catalog_id).all()
    if 'username' not in login_session or
    creator.id != login_session['user_id']:
        return render_template(
            'publicitems.html',
            items=items,
            catalog=catalog,
            creator=creator)
    else:
        return render_template(
            'items.html',
            items=items,
            catalog=catalog,
            creator=creator)


# show items information using json
@app.route('/catalog/<int:catalog_id>/json')
@app.route('/catalog/<int:catalog_id>/item/json')
def showItemsJSON(catalog_id):
    catalog = session.query(Catalog).filter_by(id=catalog_id).one()
    creator = getUserInfo(catalog.user_id)
    items = session.query(Item).filter_by(
        catalog_id=catalog_id).all()
    return jsonify(items=[item.serialize for item in items])


# show a specific item in a catalog
@app.route('/catalog/<int:catalog_id>/item/<int:item_id>')
def showItem(catalog_id, item_id):
    item = session.query(Item).filter_by(id=item_id).one()
    catalog = session.query(Catalog).filter_by(id=catalog_id).one()
    creator = getUserInfo(catalog.user_id)
    items = session.query(Item).filter_by(
        catalog_id=catalog_id).all()
    if 'username' not in login_session or
    creator.id != login_session['user_id']:
        return render_template(
            'publicitem.html',
            item=item,
            catalog=catalog,
            creator=creator)
    else:
        return render_template(
            'Item.html',
            item=item,
            catalog=catalog,
            creator=creator)

# show information about a specific item using json


@app.route('/catalog/<int:catalog_id>/item/<int:item_id>/json')
def showItemJSON(catalog_id, item_id):
    item = session.query(Item).filter_by(id=item_id).one()
    catalog = session.query(Catalog).filter_by(id=catalog_id).one()
    return jsonify(item=[item.serialize])


# create new item
@app.route('/catalog/<int:catalog_id>/new/', methods=['GET', 'POST'])
def newItem(catalog_id):
    if 'username' not in login_session:
        return redirect('/login')
    catalog = session.query(Catalog).filter_by(id=catalog_id).one()
    allcatalogs = session.query(Catalog).all()
    if login_session['user_id'] != catalog.user_id:
        return redirect(url_for('showItems', catalog_id=newItem.catalog_id))
    if request.method == 'POST':
        newItem = Item(
            name=request.form['name'],
            description=request.form['description'],
            catalog_id=request.form['catalog'],
            user_id=login_session['user_id'])
        session.add(newItem)
        session.commit()
        return redirect(url_for('showItems', catalog_id=newItem.catalog_id))
    else:
        return render_template('newitem.html', catalogs=allcatalogs)

# edit an existing item


@app.route(
    '/catalog/<int:catalog_id>item/<int:item_id>/edit',
    methods=[
        'GET',
        'POST'])
def editItem(catalog_id, item_id):
    if 'username' not in login_session:
        return redirect('/login')
    editedItem = session.query(Item).filter_by(id=item_id).one()
    catalog = session.query(Catalog).filter_by(id=catalog_id).one()
    allcatalogs = session.query(Catalog).all()
    if login_session['user_id'] != catalog.user_id:
        return redirect(
            url_for(
                'showItem',
                catalog_id=editedItem.catalog_id,
                item_id=editedItem.id))
    if request.method == 'POST':
        if request.form['name']:
            editedItem.name = request.form['name']
        if request.form['description']:
            editedItem.description = request.form['description']
        session.add(editedItem)
        session.commit()
        return redirect(
            url_for(
                'showItem',
                catalog_id=editedItem.catalog_id,
                item_id=editedItem.id))
    else:
        return render_template(
            'edititem.html',
            catalog_id=catalog_id,
            item=editedItem,
            catalogs=allcatalogs)

# delete an item


@app.route(
    '/catalog/<int:catalog_id>/item/<int:item_id>/delete',
    methods=[
        'GET',
        'POST'])
def deleteItem(catalog_id, item_id):
    if 'username' not in login_session:
        return redirect('/login')
    catalog = session.query(Catalog).filter_by(id=catalog_id).one()
    itemToDelete = session.query(Item).filter_by(id=item_id).one()
    if login_session['user_id'] != catalog.user_id:
        return redirect(url_for('showItems', catalog_id=catalog_id))
    if request.method == 'POST':
        session.delete(itemToDelete)
        session.commit()
        return redirect(url_for('showItems', catalog_id=catalog_id))
    else:
        return render_template(
            'deleteitem.html',
            item=itemToDelete,
            catalog=catalog)


if __name__ == '__main__':
    app.secret_key = 'secret_key'
    app.debug = True
    app.run(host='0.0.0.0', port=5000)
