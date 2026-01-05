import bcrypt
import hashlib
import os
from datetime import datetime, timedelta
from typing import Optional
from jose import JWTError, jwt
from fastapi import Depends, HTTPException, status, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from .database import get_db
from .models import Boutique, Session as SessionModel

SECRET_KEY = os.getenv("SESSION_SECRET", "djassa-coach-secret-key-change-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_DAYS = 7

security = HTTPBearer()

def hash_pin(pin: str) -> tuple[str, str]:
    salt = bcrypt.gensalt(rounds=12)
    pin_hash = bcrypt.hashpw(pin.encode(), salt)
    return pin_hash.decode(), salt.decode()

def verify_pin(pin: str, pin_hash: str) -> bool:
    return bcrypt.checkpw(pin.encode(), pin_hash.encode())

def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()

def create_access_token(boutique_id: str) -> str:
    expire = datetime.utcnow() + timedelta(days=ACCESS_TOKEN_EXPIRE_DAYS)
    to_encode = {"sub": boutique_id, "exp": expire}
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

async def get_current_boutique(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db)
) -> Boutique:
    token = credentials.credentials
    
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        boutique_id: str = payload.get("sub")
        if boutique_id is None:
            raise HTTPException(status_code=401, detail="Token invalide")
    except JWTError:
        raise HTTPException(status_code=401, detail="Token invalide ou expiré")
    
    token_hash = hash_token(token)
    session = db.query(SessionModel).filter(
        SessionModel.token_hash == token_hash,
        SessionModel.revoked == False,
        SessionModel.expires_at > datetime.utcnow()
    ).first()
    
    if not session:
        raise HTTPException(status_code=401, detail="Session invalide ou expirée")
    
    boutique = db.query(Boutique).filter(
        Boutique.id == boutique_id,
        Boutique.deleted_at == None,
        Boutique.active == True
    ).first()
    
    if not boutique:
        raise HTTPException(status_code=401, detail="Boutique non trouvée")
    
    return boutique

def create_session(db: Session, boutique_id: str, token: str, ip_address: str, user_agent: str = None) -> SessionModel:
    expires_at = datetime.utcnow() + timedelta(days=ACCESS_TOKEN_EXPIRE_DAYS)
    session = SessionModel(
        boutique_id=boutique_id,
        token_hash=hash_token(token),
        ip_address=ip_address,
        user_agent=user_agent,
        expires_at=expires_at
    )
    db.add(session)
    db.commit()
    return session
