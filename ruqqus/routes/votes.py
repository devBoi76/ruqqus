from urllib.parse import urlparse
import time

from ruqqus.helpers.wrappers import *
from ruqqus.helpers.base36 import *
from ruqqus.helpers.sanitize import *
from ruqqus.helpers.get import *
from ruqqus.classes import *
from flask import *
from ruqqus.__main__ import app


@app.route("/api/v1/vote/post/<post_id>/<x>", methods=["POST"])
@app.route("/api/vote/post/<post_id>/<x>", methods=["POST"])
@is_not_banned
@no_negative_balance("toast")
@api("vote")
@validate_formkey
def api_vote_post(post_id, x, v):

	if x not in ["-1", "0", "1"]:
		abort(400)

	# disallow bots
	if request.headers.get("X-User-Type","") == "Bot":
		abort(403)

	x = int(x)

	if x==-1:
		count=g.db.query(Vote).filter(
			Vote.user_id.in_(
				tuple(
					[v.id]+[x.id for x in v.alts]
					)
				),
			Vote.created_utc > (int(time.time())-3600), 
			Vote.vote_type==-1
			).count()
		if count >=15:
			return jsonify({"error": "You're doing that too much. Try again later."}), 403

	post = get_post(post_id)

	if post.is_banned:
		return jsonify({"error":"That post has been removed."}), 403
	elif post.deleted_utc > 0:
		return jsonify({"error":"That post has been deleted."}), 403
	elif post.is_archived:
		return jsonify({"error":"That post is archived and can no longer be voted on."}), 403

	# check for existing vote
	existing = g.db.query(Vote).filter_by(
		user_id=v.id, submission_id=post.id).first()
	if existing:
		existing.change_to(x)
		g.db.add(existing)

	else:
		vote = Vote(user_id=v.id,
					vote_type=x,
					submission_id=base36decode(post_id),
					creation_ip=request.remote_addr,
					app_id=v.client.application.id if v.client else None
					)

		g.db.add(vote)

	try:
		g.db.flush()
	except:
		return jsonify({"error":"Vote already exists."}), 422
		
	post.upvotes = post.ups
	post.downvotes = post.downs
	g.db.add(post)
	g.db.flush()
	post.score_disputed = post.rank_fiery
	post.score_top = post.score
	post.score_best = post.rank_best
	g.db.add(post)
	g.db.commit()
	
	now = int(time.time())
	if "100" in str(now): posts = g.db.query(Submission).options(lazyload('*')).filter_by(is_banned=False, deleted_utc=0).all()
	else:
		cutoff = now - 3600*24
		posts = g.db.query(Submission).options(lazyload('*')).filter_by(is_banned=False, deleted_utc=0).filter(Submission.created_utc > cutoff).all()

	for post in posts:
		try: 
			post.upvotes = post.ups
			post.downvotes = post.downs
			g.db.add(post)
			g.db.flush()
			post.score_disputed = post.rank_fiery
			post.score_top = post.score
			post.score_best = post.rank_best
			g.db.add(post)
		except Exception as e: print(e)
	g.db.commit()

	return "", 204


@app.route("/api/v1/vote/comment/<comment_id>/<x>", methods=["POST"])
@app.route("/api/vote/comment/<comment_id>/<x>", methods=["POST"])
@is_not_banned
@no_negative_balance("toast")
@api("vote")
@validate_formkey
def api_vote_comment(comment_id, x, v):

	if x not in ["-1", "0", "1"]:
		abort(400)

	# disallow bots
	if request.headers.get("X-User-Type","") == "Bot":
		abort(403)

	x = int(x)

	comment = get_comment(comment_id)

	if comment.is_banned:
		return jsonify({"error":"That comment has been removed."}), 403
	elif comment.deleted_utc > 0:
		return jsonify({"error":"That comment has been deleted."}), 403
	elif comment.post.is_archived:
		return jsonify({"error":"This post and its comments are archived and can no longer be voted on."}), 403

	# check for existing vote
	existing = g.db.query(CommentVote).filter_by(
		user_id=v.id, comment_id=comment.id).first()
	if existing:
		existing.change_to(x)
		g.db.add(existing)
	else:

		vote = CommentVote(user_id=v.id,
						   vote_type=x,
						   comment_id=base36decode(comment_id),
						   creation_ip=request.remote_addr,
						   app_id=v.client.application.id if v.client else None
						   )

		g.db.add(vote)
	try:
		g.db.flush()
	except:
		return jsonify({"error":"Vote already exists."}), 422

	comment.upvotes = comment.ups
	comment.downvotes = comment.downs
	g.db.add(comment)
	g.db.flush()

	try: comment.score_disputed=comment.rank_fiery
	except Exception as e: print(e)
	comment.score_hot = comment.rank_hot
	comment.score_top = comment.score

	g.db.add(comment)
	g.db.commit()

	# print(f"Vote Event: @{v.username} vote {x} on comment {comment_id}")

	return make_response(""), 204
