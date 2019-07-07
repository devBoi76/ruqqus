from werkzeug.security import generate_password_hash, check_password_hash
from flask import render_template, session
from time import strftime, time, gmtime
from sqlalchemy import *
from sqlalchemy.orm import relationship
import hmac
from os import environ
from secrets import token_hex

from teedee.helpers.base36 import *
from .ips import IP
from teedee.__main__ import Base, db

class User(Base):

    __tablename__="users"
    id = Column(BigInteger, primary_key=True)
    username = Column(String, default=None)
    email = Column(String, default=None)
    passhash = Column(String, default=None)
    created_utc = Column(BigInteger, default=0)
    admin_level = Column(Integer, default=0)
    is_banned = Column(Boolean, default=False)
    ips = relationship('IP')
    username_verified = Column(Boolean, default=False)
    over_18=Column(Boolean, default=False)
    creation_ip=Column(String, default=None)
    most_recent_ip=Column(String, default=None)
    submissions=relationship("Submission")

    def __init__(self, **kwargs):

        if "password" in kwargs:

            kwargs["passhash"]=self.hash_password(kwargs["password"])
            kwargs.pop("password")

        kwargs["created_utc"]=int(time())

        super().__init__(**kwargs)

    def update_ip(self, remote_addr):
        
        if not remote_addr==self.most_recent_ip:
            self.most_recent_ip = remote_addr
            db.add(self)

        if not remote_addr in [i.ip for i in self.ips]:
            db.add(IP(user_id=self.uid, ip=remote_addr))
        
        if db.dirty:
            db.commit()


    def hash_password(self, password):
        return generate_password_hash(password, method='pbkdf2:sha512', salt_length=8)

    def verifyPass(self, password):
        return check_password_hash(self.passhash, password)
    
    def rendered_userpage(self, v=None):

        if not self.is_banned:
            return render_template("userpage.html", u=self, v=v)
        else:
            return render_template("userpage_banned.html", u=self, v=v)

    @property
    def formkey(self):

        if "session_id" not in session:
            session["session_id"]=token_hex(16)

        return hmac.new(key=bytes(environ.get("MASTER_KEY"), "utf-16"),
                        msg=bytes(session["session_id"]+str(self.id), "utf-16")
                        ).hexdigest()

    def validate_formkey(self, formkey):

        return hmac.compare_digest(formkey, self.formkey)
    
    def verify_username(self, username):
        
        #no reassignments allowed
        if self.username_verified:
            return render_template("settings.html", v=self, error="Your account has already validated its username.")
        
        #For use when verifying username with reddit
        #Set username. Randomize username of any other existing account with same
        try:
            existing = db.query(User).filter_by(username=username).all()[0]

            #No reassignments allowed
            if existing.username_verified:
                return render_template("settings.html", v=self, error="Another account has already validated that username.")
                
            # Rename new account to user_id
            # guaranteed to be unique
            existing.username=f"user_{existing.id}"
            
            db.add(existing)
            db.commit()
                                     
        except IndexError:
            pass
                                      
        self.username=username
        self.username_verified=True
        
        db.add(self)
        db.commit()

        return render_template("settings.html", v=self, msg="Your account name has been updated and validated.")

    @property
    def url(self):
        return f"/u/{self.username}"

    @property
    def created_date(self):

        print(self.created_utc)

        return strftime("%d %B %Y", gmtime(self.created_utc))

    def __repr__(self):
        return f"<User(username={self.username})>"
