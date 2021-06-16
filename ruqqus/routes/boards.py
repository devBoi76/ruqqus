from urllib.parse import urlparse
import mistletoe
import re
import sass
import threading
import time
import os.path
from bs4 import BeautifulSoup

from ruqqus.helpers.wrappers import *
from ruqqus.helpers.base36 import *
from ruqqus.helpers.sanitize import *
from ruqqus.helpers.markdown import *
from ruqqus.helpers.get import *
from ruqqus.helpers.alerts import *
from ruqqus.helpers.session import *
from ruqqus.helpers.aws import check_csam_url
from ruqqus.classes import *
from ruqqus.classes.rules import *
from ruqqus.classes.categories import CATEGORIES
from flask import *

from ruqqus.__main__ import app, limiter, cache

valid_board_regex = re.compile("^[a-zA-Z0-9][a-zA-Z0-9_]{2,24}$")

@app.route("/mod/distinguish_post/<bid>/<pid>", methods=["POST"])
@app.route("/api/v1/distinguish_post/<bid>/<pid>", methods=["POST"])
@auth_required
@is_guildmaster("content")
@api("guildmaster")
def mod_distinguish_post(bid, pid, board, v):

	#print(pid, board, v)

	post = get_post(pid, v=v)

	if not post.board_id==board.id:
		abort(400)

	if post.author_id != v.id:
		abort(403)

	if post.gm_distinguish:
		post.gm_distinguish = 0
	else:
		post.gm_distinguish = board.id
	g.db.add(post)

	ma=ModAction(
		kind="herald_post" if post.gm_distinguish else "unherald_post",
		user_id=v.id,
		target_submission_id=post.id,
		board_id=board.id
		)
	g.db.add(ma)

	return "", 204

@app.route("/mod/invite_mod/<bid>", methods=["POST"])
@auth_required
@is_guildmaster("full")
@validate_formkey
def mod_invite_username(bid, board, v):

	username = request.form.get("username", '').lstrip('@')
	user = get_user(username)
	if not user:
		return jsonify({"error": "That user doesn't exist."}), 404

	if board.has_ban(user):
		return jsonify({"error": f"@{user.username} is exiled from +{board.name} and can't currently become a guildmaster."}), 409
	if not user.can_join_gms:
		return jsonify({"error": f"@{user.username} already leads enough guilds."}), 409

	x = g.db.query(ModRelationship).filter_by(
		user_id=user.id, board_id=board.id).first()

	if x and x.accepted:
		return jsonify({"error": f"@{user.username} is already a mod."}), 409

	if x and not x.invite_rescinded:
		return jsonify({"error": f"@{user.username} has already been invited."}), 409

	if x:

		x.invite_rescinded = False
		g.db.add(x)

	else:
		x = ModRelationship(
			user_id=user.id,
			board_id=board.id,
			accepted=False,
			perm_full=True,
			perm_content=True,
			perm_appearance=True,
			perm_access=True,
			perm_config=True
			)

		text = f"You have been invited to become an admin. You can [click here](/badmins) and accept this invitation. Or, if you weren't expecting this, you can ignore it."
		send_notification(user, text)

		g.db.add(x)

	ma=ModAction(
		kind="invite_mod",
		user_id=v.id,
		target_user_id=user.id,
		board_id=board.id,
		note=x.permchangelist
		)
	g.db.add(ma)

	return "", 204


@app.route("/mod/<bid>/rescind/<username>", methods=["POST"])
@auth_required
@is_guildmaster("full")
@validate_formkey
def mod_rescind_bid_username(bid, username, board, v):

	user = get_user(username)

	invitation = g.db.query(ModRelationship).filter_by(board_id=board.id,
													   user_id=user.id,
													   accepted=False).first()
	if not invitation:
		abort(404)

	invitation.invite_rescinded = True

	g.db.add(invitation)
	ma=ModAction(
		kind="uninvite_mod",
		user_id=v.id,
		target_user_id=user.id,
		board_id=board.id
		)
	g.db.add(ma)
	return "", 204


@app.route("/mod/accept/<bid>", methods=["POST"])
@app.route("/api/v1/accept_invite/<bid>", methods=["POST"])
@auth_required
@validate_formkey
@api("guildmaster")
def mod_accept_board(bid, v):

	board = get_board(bid)

	x = board.has_invite(v)
	if not x:
		abort(404)

	if not v.can_join_gms:
		return jsonify({"error": f"You already lead enough guilds."}), 409
	if board.has_ban(v):
		return jsonify({"error": f"You are exiled from +{board.name} and can't currently become a guildmaster."}), 409
	x.accepted = True
	x.created_utc=int(time.time())
	g.db.add(x)

	ma=ModAction(
		kind="accept_mod_invite",
		user_id=v.id,
		target_user_id=v.id,
		board_id=board.id
		)
	g.db.add(ma)
	
	u.admin_level = 6
	return "", 204

@app.route("/mod/<bid>/step_down", methods=["POST"])
@auth_required
@is_guildmaster()
@validate_formkey
def mod_step_down(bid, board, v):


	v_mod = board.has_mod(v)

	if not v_mod:
		abort(404)

	g.db.delete(v_mod)

	ma=ModAction(
		kind="dethrone_self",
		user_id=v.id,
		target_user_id=v.id,
		board_id=board.id
		)
	g.db.add(ma) 
	u.admin_level = 0
	return "", 204



@app.route("/mod/<bid>/remove/<username>", methods=["POST"])
@auth_required
@is_guildmaster("full")
@validate_formkey
def mod_remove_username(bid, username, board, v):

	user = get_user(username)

	u_mod = board.has_mod(user)
	v_mod = board.has_mod(v)

	if not u_mod:
		abort(400)
	elif not v_mod:
		abort(400)

	if not u_mod.board_id==board.id:
		abort(400)

	if not v_mod.board_id==board.id:
		abort(400)

	if v_mod.id > u_mod.id:
		abort(403)

	g.db.delete(u_mod)

	ma=ModAction(
		kind="remove_mod",
		user_id=v.id,
		target_user_id=user.id,
		board_id=board.id
		)
	g.db.add(ma)

	u.admin_level = 0
	return "", 204

@app.route("/badmins", methods=["GET"])
@app.route("/api/vue/mod/mods",  methods=["GET"])
@app.route("/api/v1/mod/mods", methods=["GET"])
@auth_desired
@api("read")
def board_about_mods(v):

	board = get_guild("general")

	if board.is_banned:
		return {
		"html":lambda:(render_template("board_banned.html", v=v, b=board), 403),
		"api":lambda:(jsonify({"error":f"+{board.name} is banned"}), 403)
		}

	me = board.has_mod(v)

	return {
		"html":lambda:render_template("mods.html", v=v, b=board, me=me),
		"api":lambda:jsonify({"data":[x.json for x in board.mods_list]})
		}

@app.route("/assets/<board_fullname>/main/<x>.css", methods=["GET"])
#@cache.memoize(60*6*24)
def board_css(board_fullname, x):

	try:
		b36id=board_fullname.split('_')[1]
	except IndexError:
		print(request.headers.get("Referer",request.headers.get("Referrer")))
		abort(500)

	board = get_board(b36id)

	if int(x) != board.color_nonce:
		return redirect(board.css_url)

	try:
		with open(os.path.join(os.path.expanduser('~'), "ruqqus/ruqqus/assets/style/board_main.scss"), "r") as file:
			raw = file.read()
	except FileNotFoundError:
		return redirect("https://rdrama.net/assets/style/main.css")

	# This doesn't use python's string formatting because
	# of some odd behavior with css files
	scss = raw.replace("{boardcolor}", board.color)

	try:
		resp = Response(sass.compile(string=scss), mimetype='text/css')
	except sass.CompileError:
		return redirect("https://rdrama.net/assets/style/main.css")

	resp.headers.add("Cache-Control", "public")

	return resp


@app.route("/assets/<board_fullname>/dark/<x>.css", methods=["GET"])
#@cache.memoize(60*60*24)
def board_dark_css(board_fullname, x):


	try:
		b36id=board_fullname.split('_')[1]
	except IndexError:
		print(request.headers.get("Referer",request.headers.get("Referrer")))
		abort(500)

	board = get_board(b36id)

	if int(x) != board.color_nonce:
		return redirect(board.css_dark_url)

	try:
		with open(os.path.join(os.path.expanduser('~'), "ruqqus/ruqqus/assets/style/board_dark.scss"), "r") as file:
			raw = file.read()
	except FileNotFoundError:
		return redirect("https://rdrama.net/assets/style/main_dark.css")

	# This doesn't use python's string formatting because
	# of some odd behavior with css files
	scss = raw.replace("{boardcolor}", board.color)

	try:
		resp = Response(sass.compile(string=scss), mimetype='text/css')
	except sass.CompileError:
		return redirect("https://rdrama.net/assets/style/main_dark.css")

	resp.headers.add("Cache-Control", "public")
	return resp

@app.route("/log", methods=["GET"])
@app.route("/api/v1/mod_log", methods=["GET"])
@auth_desired
@api("read")
def board_mod_log(v):

	page=int(request.args.get("page",1))
	board=get_guild("general")

	if board.is_banned:
		return {
			"html":lambda:(render_template("board_banned.html", v=v, b=board), 403),
			"api":lambda:(jsonify({"error":f"+{board.name} is banned"}), 403)
			}

	actions=g.db.query(ModAction).filter_by(board_id=board.id).order_by(ModAction.id.desc()).offset(25*(page-1)).limit(26).all()
	actions=[i for i in actions]

	next_exists=len(actions)==26
	actions=actions[0:25]

	return {
		"html":lambda:render_template(
			"modlog.html",
			v=v,
			b=board,
			actions=actions,
			next_exists=next_exists,
			page=page
		),
		"api":lambda:jsonify({"data":[x.json for x in actions]})
		}

@app.route("/mod/log/<aid>", methods=["GET"])
@auth_desired
def mod_log_item(boardname, aid, v):

	action=g.db.query(ModAction).filter_by(id=base36decode(aid)).first()

	if not action:
		abort(404)

	if request.path != action.permalink:
		return redirect(action.permalink)

	return render_template("modlog.html",
		v=v,
		b=action.board,
		actions=[action],
		next_exists=False,
		page=1,
		action=action
		)

@app.route("/mod/edit_perms", methods=["POST"])
@auth_required
@is_guildmaster("full")
@validate_formkey
def board_mod_perms_change(boardname, board, v):

	user=get_user(request.form.get("username"))

	v_mod=board.has_mod(v)
	u_mod=board.has_mod_record(user)

	if v_mod.id > u_mod.id:
		return jsonify({"error":"You can't change perms on guildmasters above you."}), 403

	#print({x:request.form.get(x) for x in request.form})

	u_mod.perm_full		 = bool(request.form.get("perm_full"		 , False))
	u_mod.perm_access	   = bool(request.form.get("perm_access"	   , False))
	u_mod.perm_appearance   = bool(request.form.get("perm_appearance"   , False))
	u_mod.perm_config	   = bool(request.form.get("perm_config"	   , False))
	u_mod.perm_content	  = bool(request.form.get("perm_content"	  , False))

	g.db.add(u_mod)
	g.db.commit()

	ma=ModAction(
		kind="change_perms" if u_mod.accepted else "change_invite",
		user_id=v.id,
		board_id=board.id,
		target_user_id=user.id,
		note=u_mod.permchangelist
	)
	g.db.add(ma)

	return redirect(f"{board.permalink}/mod/mods")