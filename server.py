from fastapi import FastAPI, HTTPException, Request, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import sqlite3
import json
from typing import Optional, List, Dict, Any

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def get_db():
    conn = sqlite3.connect("cv_bank.db")
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    cursor = conn.cursor()
    cursor.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE,
            name TEXT,
            role TEXT,
            country TEXT,
            phone TEXT,
            language TEXT DEFAULT 'en'
        );

        CREATE TABLE IF NOT EXISTS creator_settings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            bank_account TEXT
        );

        CREATE TABLE IF NOT EXISTS cvs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            name TEXT,
            email TEXT,
            phone TEXT,
            country TEXT,
            designation TEXT,
            experience_years INTEGER,
            skills TEXT,
            summary TEXT,
            education TEXT,
            location TEXT,
            notice_period TEXT,
            raw_text TEXT,
            is_bank INTEGER DEFAULT 1,
            target_recruiter_id INTEGER,
            is_priority INTEGER DEFAULT 0,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS shortlisted_cvs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cv_id INTEGER,
            recruiter_id INTEGER,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(cv_id) REFERENCES cvs(id),
            FOREIGN KEY(recruiter_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS profile_views (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cv_id INTEGER,
            viewer_id INTEGER,
            viewed_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(cv_id) REFERENCES cvs(id),
            FOREIGN KEY(viewer_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            author_id INTEGER,
            target_id INTEGER,
            rating INTEGER,
            comment TEXT,
            type TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(author_id) REFERENCES users(id)
        );
    """)
    conn.commit()
    conn.close()

init_db()

class LoginRequest(BaseModel):
    email: str
    name: str
    role: str
    country: Optional[str] = None
    phone: Optional[str] = None
    language: Optional[str] = 'en'

@app.post("/api/auth/login")
def login(req: LoginRequest):
    if req.role == 'creator' and req.email != 'rkcortezlee@gmail.com':
        raise HTTPException(status_code=403, detail="Unauthorized. Only the designated creator can log in to this panel.")
    
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM users WHERE email = ?", (req.email,))
    user = cursor.fetchone()
    
    if not user:
        cursor.execute(
            "INSERT INTO users (email, name, role, country, phone, language) VALUES (?, ?, ?, ?, ?, ?)",
            (req.email, req.name, req.role, req.country, req.phone, req.language)
        )
        conn.commit()
        user_id = cursor.lastrowid
        user_dict = {
            "id": user_id, "email": req.email, "name": req.name, 
            "role": req.role, "country": req.country, "phone": req.phone, "language": req.language
        }
    else:
        user_dict = dict(user)
        if user_dict['role'] != req.role:
            raise HTTPException(status_code=403, detail=f"This account is registered as a {user_dict['role']}. You cannot log in as a {req.role}.")
        
        if req.language and req.language != user_dict['language']:
            cursor.execute("UPDATE users SET language = ? WHERE id = ?", (req.language, user_dict['id']))
            conn.commit()
            user_dict['language'] = req.language
            
    conn.close()
    return user_dict

class CVRequest(BaseModel):
    user_id: int
    name: str
    email: str
    phone: Optional[str] = None
    country: Optional[str] = None
    designation: str
    experience_years: int
    skills: List[str]
    summary: str
    education: str
    location: str
    notice_period: str
    raw_text: str
    is_bank: bool = True
    target_recruiter_id: Optional[int] = None

@app.post("/api/cvs")
def create_cv(req: CVRequest):
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            INSERT INTO cvs (user_id, name, email, phone, country, designation, experience_years, skills, summary, education, location, notice_period, raw_text, is_bank, target_recruiter_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            req.user_id, req.name, req.email, req.phone, req.country, req.designation, 
            req.experience_years, json.dumps(req.skills), req.summary, req.education, 
            req.location, req.notice_period, req.raw_text, 1 if req.is_bank else 0, req.target_recruiter_id
        ))
        conn.commit()
        return {"id": cursor.lastrowid, "success": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail="Failed to save CV")
    finally:
        conn.close()

class ViewRequest(BaseModel):
    viewer_id: int

@app.post("/api/cvs/{id}/view")
def track_view(id: int, req: ViewRequest):
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT INTO profile_views (cv_id, viewer_id) VALUES (?, ?)", (id, req.viewer_id))
        conn.commit()
        return {"success": True}
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to track view")
    finally:
        conn.close()

@app.get("/api/cvs/my-status")
def my_status(user_id: int):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM cvs WHERE user_id = ?", (user_id,))
    cv = cursor.fetchone()
    
    if not cv:
        conn.close()
        return {"cv": None, "views": []}
        
    cursor.execute("""
        SELECT pv.*, u.name as viewer_name 
        FROM profile_views pv 
        JOIN users u ON pv.viewer_id = u.id 
        WHERE pv.cv_id = ?
        ORDER BY viewed_at DESC
    """, (cv['id'],))
    views = cursor.fetchall()
    
    cv_dict = dict(cv)
    cv_dict['skills'] = json.loads(cv_dict['skills']) if cv_dict['skills'] else []
    
    conn.close()
    return {"cv": cv_dict, "views": [dict(v) for v in views]}

@app.get("/api/recruiters")
def get_recruiters():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id, name, email FROM users WHERE role = 'recruiter'")
    recruiters = cursor.fetchall()
    conn.close()
    return [dict(r) for r in recruiters]

class ReviewRequest(BaseModel):
    author_id: int
    target_id: Optional[int] = None
    rating: int
    comment: str
    type: str

@app.post("/api/reviews")
def create_review(req: ReviewRequest):
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT INTO reviews (author_id, target_id, rating, comment, type) VALUES (?, ?, ?, ?, ?)",
                       (req.author_id, req.target_id, req.rating, req.comment, req.type))
        conn.commit()
        return {"success": True}
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to save review")
    finally:
        conn.close()

@app.get("/api/reviews")
def get_reviews(type: Optional[str] = None, target_id: Optional[int] = None):
    conn = get_db()
    cursor = conn.cursor()
    query = "SELECT r.*, u.name as author_name FROM reviews r JOIN users u ON r.author_id = u.id"
    params = []
    
    if type:
        query += " WHERE r.type = ?"
        params.append(type)
        if target_id:
            query += " AND r.target_id = ?"
            params.append(target_id)
            
    query += " ORDER BY r.created_at DESC"
    cursor.execute(query, params)
    reviews = cursor.fetchall()
    conn.close()
    return [dict(r) for r in reviews]

@app.post("/api/cvs/{id}/priority")
def make_priority(id: int):
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("UPDATE cvs SET is_priority = 1 WHERE id = ?", (id,))
        conn.commit()
        return {"success": True}
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to upgrade CV")
    finally:
        conn.close()

@app.get("/api/creator/settings")
def get_creator_settings():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM creator_settings LIMIT 1")
    settings = cursor.fetchone()
    
    if not settings:
        cursor.execute("INSERT INTO creator_settings (bank_account) VALUES (?)", (""))
        conn.commit()
        settings = {"bank_account": ""}
    else:
        settings = dict(settings)
        
    conn.close()
    return settings

class CreatorSettingsRequest(BaseModel):
    bank_account: str

@app.post("/api/creator/settings")
def save_creator_settings(req: CreatorSettingsRequest):
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("UPDATE creator_settings SET bank_account = ?", (req.bank_account,))
        conn.commit()
        return {"success": True}
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to save settings")
    finally:
        conn.close()

@app.get("/api/creator/users")
def get_all_users():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users")
    users = cursor.fetchall()
    conn.close()
    return [dict(u) for u in users]

class ShortlistRequest(BaseModel):
    recruiter_id: int

@app.post("/api/cvs/{id}/shortlist")
def toggle_shortlist(id: int, req: ShortlistRequest):
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT id FROM shortlisted_cvs WHERE cv_id = ? AND recruiter_id = ?", (id, req.recruiter_id))
        existing = cursor.fetchone()
        
        if existing:
            cursor.execute("DELETE FROM shortlisted_cvs WHERE cv_id = ? AND recruiter_id = ?", (id, req.recruiter_id))
            conn.commit()
            return {"success": True, "shortlisted": False}
        else:
            cursor.execute("INSERT INTO shortlisted_cvs (cv_id, recruiter_id) VALUES (?, ?)", (id, req.recruiter_id))
            conn.commit()
            return {"success": True, "shortlisted": True}
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to toggle shortlist")
    finally:
        conn.close()

@app.get("/api/cvs/shortlisted")
def get_shortlisted(recruiter_id: int):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT cv.* FROM cvs cv
        JOIN shortlisted_cvs sc ON cv.id = sc.cv_id
        WHERE sc.recruiter_id = ?
    """, (recruiter_id,))
    rows = cursor.fetchall()
    
    formatted_rows = []
    for row in rows:
        d = dict(row)
        d['skills'] = json.loads(d['skills']) if d['skills'] else []
        formatted_rows.append(d)
        
    conn.close()
    return formatted_rows

@app.get("/api/cvs")
def get_cvs(
    designation: Optional[str] = None, 
    user_role: Optional[str] = None, 
    user_id: Optional[int] = None,
    experience: Optional[str] = None,
    education: Optional[str] = None,
    skills: Optional[str] = None,
    location: Optional[str] = None,
    notice: Optional[str] = None
):
    if user_role == 'applicant':
        raise HTTPException(status_code=403, detail="Applicants cannot view the CV bank")
        
    conn = get_db()
    cursor = conn.cursor()
    
    recruiter_country = None
    if user_id and user_role == 'recruiter':
        cursor.execute("SELECT country FROM users WHERE id = ?", (user_id,))
        recruiter = cursor.fetchone()
        if recruiter:
            recruiter_country = recruiter['country']
            
    query = "SELECT * FROM cvs"
    params = []
    where_clauses = []
    
    if designation:
        where_clauses.append("designation LIKE ?")
        params.append(f"%{designation}%")
        
    if experience:
        where_clauses.append("experience_years >= ?")
        params.append(int(experience))
        
    if education:
        where_clauses.append("education LIKE ?")
        params.append(f"%{education}%")
        
    if skills:
        where_clauses.append("skills LIKE ?")
        params.append(f"%{skills}%")
        
    if location:
        where_clauses.append("location LIKE ?")
        params.append(f"%{location}%")
        
    if notice:
        where_clauses.append("notice_period LIKE ?")
        params.append(f"%{notice}%")
        
    if user_role == 'recruiter':
        where_clauses.append("(is_bank = 1 OR target_recruiter_id = ?)")
        params.append(user_id)
        
    if where_clauses:
        query += " WHERE " + " AND ".join(where_clauses)
        
    if recruiter_country:
        query += " ORDER BY is_priority DESC, (CASE WHEN country = ? THEN 1 ELSE 0 END) DESC, created_at DESC"
        params.append(recruiter_country)
    else:
        query += " ORDER BY is_priority DESC, created_at DESC"
        
    cursor.execute(query, params)
    rows = cursor.fetchall()
    
    formatted_rows = []
    for row in rows:
        d = dict(row)
        d['skills'] = json.loads(d['skills']) if d['skills'] else []
        formatted_rows.append(d)
        
    conn.close()
    return formatted_rows

# To run this server, you would use:
# uvicorn server:app --host 0.0.0.0 --port 3000
