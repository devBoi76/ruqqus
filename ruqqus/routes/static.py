import time
import jinja2
import pyotp
import pprint
import sass
from flask import *

from ruqqus.helpers.wrappers import *
import ruqqus.classes
from ruqqus.classes import *
from ruqqus.mail import *
from ruqqus.__main__ import app, limiter

# take care of misc pages that never really change (much)

@app.route("/assets/style/<file>.css", methods=["GET"])
#@cache.memoize(60*6*24)
def main_css(file):

	#print(file, color)

	if file not in ["main", "main_dark"]:
		abort(404)

	try:
		name=f"ruqqus/ruqqus/assets/style/{file}.scss"
		#print(name)
		with open(os.path.join(os.path.expanduser('~'), name), "r") as file:
			raw = file.read()

	except FileNotFoundError:
		#rint("unable to find file")
		return make_response(send_file(f'~/ruqqus/ruqqus/assets/style/{file}.css'))

	# This doesn't use python's string formatting because
	# of some odd behavior with css files
	scss = raw.replace("{boardcolor}", app.config["SITE_COLOR"])
	scss = scss.replace("{maincolor}", app.config["SITE_COLOR"])


	try:
		resp = Response(sass.compile(string=scss), mimetype='text/css')
	except sass.CompileError as e:
		#print(e)
		return make_response(send_file(f'./assets/style/{file}.css'))

	resp.headers.add("Cache-Control", "public")

	return resp

@app.route('/assets/<path:path>')
@limiter.exempt
def static_service(path):
	resp = make_response(send_from_directory('./assets', path))
	resp.headers.add("Cache-Control", "public")

	if request.path.endswith('.css'):
		resp.headers.add("Content-Type", "text/css")
	return resp


@app.route("/robots.txt", methods=["GET"])
def robots_txt():
	return send_file("./assets/robots.txt")


@app.route("/slurs.txt", methods=["GET"])
def slurs():
	resp = make_response('\n'.join([x.keyword for x in g.db.query(
		BadWord).order_by(BadWord.keyword.asc()).all()]))
	resp.headers.add("Content-Type", "text/plain")
	return resp


@app.route("/settings", methods=["GET"])
@auth_required
def settings(v):
	return redirect("/settings/profile")


@app.route("/settings/profile", methods=["GET"])
@auth_required
def settings_profile(v):
	return render_template("settings_profile.html",
						   v=v)


@app.route("/help/titles", methods=["GET"])
@auth_desired
def titles(v):
	titles = [x for x in g.db.query(Title).order_by(text("id asc")).all()]
	return render_template("/help/titles.html",
						   v=v,
						   titles=titles)


@app.route("/help/terms", methods=["GET"])
@auth_desired
def help_terms(v):

	cutoff = int(environ.get("tos_cutoff", 0))

	return render_template("/help/terms.html",
						   v=v,
						   cutoff=cutoff)


@app.route("/help/badges", methods=["GET"])
@auth_desired
def badges(v):
	badges = [
		x for x in g.db.query(BadgeDef).order_by(
			text("rank asc, id asc")).all()]
	return render_template("help/badges.html",
						   v=v,
						   badges=badges)


@app.route("/help/admins", methods=["GET"])
@auth_desired
def help_admins(v):

	admins = g.db.query(User).filter(
		User.admin_level > 1,
		User.id > 1).order_by(
		User.id.asc()).all()
	admins = [x for x in admins]

	exadmins = g.db.query(User).filter_by(
		admin_level=1).order_by(
		User.id.asc()).all()
	exadmins = [x for x in exadmins]

	return render_template("help/admins.html",
						   v=v,
						   admins=admins,
						   exadmins=exadmins
						   )


@app.route("/settings/security", methods=["GET"])
@auth_required
def settings_security(v):
    mfa_secret=pyotp.random_base32() if not v.mfa_secret else None
    if mfa_secret:
        recovery=f"{mfa_secret}+{v.id}+{v.original_username}"
        recovery=generate_hash(recovery)
        recovery=base36encode(int(recovery,16))
        while len(recovery)<25:
            recovery="0"+recovery
        recovery=" ".join([recovery[i:i+5] for i in range(0,len(recovery),5)])
    else:
        recovery=None
    return render_template(
            "settings_security.html",
            v=v,
            mfa_secret=mfa_secret,
            recovery=recovery,
            error=request.args.get("error") or None,
            msg=request.args.get("msg") or None
        )

@app.route("/settings/premium", methods=["GET"])
@auth_required
def settings_premium(v):
	return render_template("settings_premium.html",
						   v=v,
						   error=request.args.get("error") or None,
						   msg=request.args.get("msg") or None
						   )

@app.route("/assets/favicon.ico", methods=["GET"])
def favicon():
	return send_file("./assets/images/logo/favicon.png")


#@app.route("/my_info", methods=["GET"])
#@auth_required
#def my_info(v):
#    return render_template("my_info.html", v=v)


@app.route("/about/<path:path>")
def about_path(path):
	return redirect(f"/help/{path}")


@app.route("/help/<path:path>", methods=["GET"])
@auth_desired
def help_path(path, v):
	try:
		return render_template(safe_join("help", path + ".html"), v=v)
	except jinja2.exceptions.TemplateNotFound:
		abort(404)


@app.route("/help", methods=["GET"])
@auth_desired
def help_home(v):
	return render_template("help.html", v=v)


@app.route("/help/submit_contact", methods=["POST"])
@is_not_banned
@validate_formkey
def press_inquiry(v):

	data = [(x, request.form[x]) for x in request.form if x != "formkey"]
	data.append(("username", v.username))
	data.append(("email", v.email))

	data = sorted(data, key=lambda x: x[0])

	if request.form.get("press"):
		email_template = "email/press.html"
	else:
		email_template = "email/contactform.html"

	try:
		send_mail(environ.get("admin_email"),
				  "Press Submission",
				  render_template(email_template,
								  data=data
								  ),
				  plaintext=str(data)
				  )
	except BaseException:
		return render_template("/help/press.html",
							   error="Unable to save your inquiry. Please try again later.",
							   v=v)

	return render_template("/help/press.html",
						   msg="Your inquiry has been saved.",
						   v=v)


@app.route("/info/image_hosts", methods=["GET"])
def info_image_hosts():

	sites = g.db.query(Domain).filter_by(
		show_thumbnail=True).order_by(
		Domain.domain.asc()).all()

	sites = [x.domain for x in sites]

	text = "\n".join(sites)

	resp = make_response(text)
	resp.mimetype = "text/plain"
	return resp

@app.route("/dismiss_mobile_tip", methods=["POST"])
def dismiss_mobile_tip():

	session["tooltip_last_dismissed"]=int(time.time())
	session.modified=True

	return "", 204

