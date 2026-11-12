from fastapi import FastAPI, UploadFile, File, HTTPException, status, Query
from pydantic import BaseModel
from typing import List
from bs4 import BeautifulSoup
import re

app = FastAPI()

# --- Global In-Memory Storage ---
course_catalog = {}
db = {}

# --- Pydantic Models for JSON Validation ---
class CourseRecord(BaseModel):
    course_code: str
    term: str
    credits_earned: int
    status: str

class PlanRecord(BaseModel):
    course_code: str
    term: str

class HistoryUpdate(BaseModel):
    history: List[CourseRecord]

class PlanUpdate(BaseModel):
    planned_courses: List[PlanRecord]

class StudentProfile(BaseModel):
    student_id: str
    history: List[CourseRecord]
    plan: List[PlanRecord]

# --- PHASE 1: Catalog Logic ---
@app.post("/api/v1/admin/catalog/import")
async def import_catalog(file: UploadFile = File(...)):
    contents = await file.read()
    soup = BeautifulSoup(contents, 'html.parser')
    table = soup.find('table')
    if not table:
        raise HTTPException(status_code=400, detail="No table found in the uploaded HTML document.")
        
    rows = table.find_all('tr')[1:]
    courses_added = 0
    for row in rows:
        cols = row.find_all('td')
        if len(cols) >= 5:
            course_code = cols[0].text.strip()
            title = cols[1].text.strip()
            credits_text = cols[2].text.strip()
            prereqs_raw = cols[3].text.strip()
            cross_listed_raw = cols[4].text.strip()
            
            course_code_pattern = r'[A-Z]{4}\s\d{4}'
            prereqs = re.findall(course_code_pattern, prereqs_raw) if prereqs_raw.lower() != 'none' else []
            cross_listed = re.findall(course_code_pattern, cross_listed_raw) if cross_listed_raw.lower() != 'none' else []
            
            course_catalog[course_code] = {
                "course_code": course_code,
                "title": title,
                "credits": int(credits_text) if credits_text.isdigit() else credits_text,
                "prerequisites": prereqs,
                "cross_listed": cross_listed
            }
            courses_added += 1
            
    return {"message": f"Successfully ingested {courses_added} courses into memory."}

@app.get("/api/v1/catalog/courses/{course_code}")
async def get_course(course_code: str):
    formatted_code = course_code[:4].upper() + " " + course_code[4:] if len(course_code) >= 8 and " " not in course_code else course_code.upper()
    if formatted_code not in course_catalog:
        raise HTTPException(status_code=404, detail="Course not found in catalog.")
    return course_catalog[formatted_code]


# --- PHASE 2: Student Logic ---
def parse_transcript_html(html_content: bytes) -> List[dict]:
    soup = BeautifulSoup(html_content, 'html.parser')
    extracted_courses = {}

    for table in soup.find_all('table'):
        rows = table.find_all('tr')
        if not rows: continue
        headers = [th.get_text(strip=True).lower() for th in rows[0].find_all(['th', 'td'])]
        col_idx = {}
        for i, header_text in enumerate(headers):
            if 'status' in header_text: col_idx['status'] = i
            elif 'course' in header_text: col_idx['course'] = i
            elif 'grade' in header_text: col_idx['grade'] = i
            elif 'term' in header_text: col_idx['term'] = i
            elif 'credits' in header_text: col_idx['credits'] = i
            
        if len(col_idx) < 5: continue
            
        for row in rows[1:]:
            cells = row.find_all(['td', 'th'])
            if len(cells) <= max(col_idx.values()): continue
                
            status_val = cells[col_idx['status']].get_text(strip=True)
            term_val = cells[col_idx['term']].get_text(strip=True)
            
            if status_val not in ['Completed', 'In-Progress', 'Attempted']: continue
            if not term_val: continue
                
            course_val = cells[col_idx['course']].get_text(strip=True)
            grade_val = cells[col_idx['grade']].get_text(strip=True)
            credits_str = cells[col_idx['credits']].get_text(strip=True)
            
            try: credits_val = int(credits_str)
            except ValueError: credits_val = 0
                
            try:
                float(grade_val)
                grade_score = 3
            except ValueError:
                if grade_val and grade_val.upper() != 'P': grade_score = 2
                else: grade_score = 1
                    
            record_key = (course_val, term_val)
            current_rank = (grade_score, credits_val)
            
            if record_key not in extracted_courses or current_rank > extracted_courses[record_key][0]:
                extracted_courses[record_key] = (current_rank, {
                    "course_code": course_val,
                    "term": term_val,
                    "credits_earned": credits_val,
                    "status": status_val
                })
                
    return [v[1] for v in extracted_courses.values()]

@app.post("/api/v1/students/{student_id}/history/import", status_code=status.HTTP_201_CREATED)
async def import_history(student_id: str, file: UploadFile = File(...)):
    contents = await file.read()
    parsed_history = parse_transcript_html(contents)
    if student_id not in db: db[student_id] = {"history": [], "plan": []}
    db[student_id]["history"] = parsed_history
    return {"status": "success", "past_courses_imported": len(parsed_history)}

@app.put("/api/v1/students/{student_id}/history")
def update_history(student_id: str, payload: HistoryUpdate):
    if student_id not in db: raise HTTPException(status_code=404, detail="Student not found")
    db[student_id]["history"] = [item.dict() for item in payload.history]
    return {"status": "success", "message": "Academic history updated successfully"}

@app.delete("/api/v1/students/{student_id}/history")
def delete_history(student_id: str):
    if student_id not in db: raise HTTPException(status_code=404, detail="Student not found")
    db[student_id]["history"] = []
    return {"status": "success", "message": "Academic history cleared"}

@app.post("/api/v1/students/{student_id}/plan")
def create_plan(student_id: str, payload: PlanUpdate):
    if student_id not in db: raise HTTPException(status_code=404, detail="Student not found")
    db[student_id]["plan"] = [item.dict() for item in payload.planned_courses]
    return {"status": "success", "planned_courses_saved": len(payload.planned_courses)}

@app.put("/api/v1/students/{student_id}/plan")
def update_plan(student_id: str, payload: PlanUpdate):
    if student_id not in db: raise HTTPException(status_code=404, detail="Student not found")
    db[student_id]["plan"] = [item.dict() for item in payload.planned_courses]
    return {"status": "success", "planned_courses_saved": len(payload.planned_courses)}

@app.delete("/api/v1/students/{student_id}/plan")
def delete_plan(student_id: str):
    if student_id not in db: raise HTTPException(status_code=404, detail="Student not found")
    db[student_id]["plan"] = []
    return {"status": "success", "message": "Plan cleared"}

@app.get("/api/v1/students/{student_id}/profile", response_model=StudentProfile)
def get_profile(student_id: str):
    if student_id not in db: raise HTTPException(status_code=404, detail="Student not found")
    return {"student_id": student_id, "history": db[student_id]["history"], "plan": db[student_id]["plan"]}


# --- PHASE 3: Audit Engine Logic ---
def normalize_code(code: str) -> str:
    return re.sub(r'[^A-Z0-9]', '', code.upper())

def term_rank(term: str) -> int:
    season_order = {"W": 1, "SP": 2, "S": 3, "F": 4}
    return int(term[:2]) * 10 + season_order.get(term[2:], 0)

@app.get("/api/v1/students/{student_id}/audit-report")
def get_audit_report(student_id: str, strict: bool = Query(False)):
    if student_id not in db:
        raise HTTPException(status_code=404, detail="Student not found")

    student_history = db[student_id].get("history", [])
    student_plan = db[student_id].get("plan", [])

    timeline_errors = {}
    cross_list_violations = []
    earned_credits = 0
    planned_credits = 0
    completed_codes = set()

    for course in student_history:
        if course.get('status') == 'Completed':
            norm_code = normalize_code(course['course_code'])
            if norm_code not in completed_codes:
                earned_credits += course.get('credits_earned', 0)
                completed_codes.add(norm_code)

    for course in student_plan:
        norm_code = normalize_code(course['course_code'])
        term = course['term']
        
        cat_data = {}
        for k, v in course_catalog.items():
            if normalize_code(k) == norm_code:
                cat_data = v
                break

        if isinstance(cat_data.get('credits'), int):
            planned_credits += cat_data['credits']

        for cross_list in cat_data.get('cross_listed', []):
            if normalize_code(cross_list) in completed_codes:
                cross_list_violations.append({
                    "course_code": course['course_code'],
                    "type": "CROSS_LIST_CONFLICT",
                    "message": f"Cross-listed with completed course {cross_list}"
                })

        for prereq in cat_data.get('prerequisites', []):
            if normalize_code(prereq) not in completed_codes:
                if term not in timeline_errors: timeline_errors[term] = []
                timeline_errors[term].append({
                    "course_code": course['course_code'],
                    "type": "MISSING_PREREQUISITE",
                    "message": f"Missing prerequisite: {prereq}"
                })

    timeline_validation = [
        {"term": t, "errors": timeline_errors[t]}
        for t in sorted(timeline_errors.keys(), key=term_rank)
    ]

    has_issues = len(timeline_validation) > 0 or len(cross_list_violations) > 0
    
    if not has_issues: final_status = "ok"
    elif strict: final_status = "failed"
    else: final_status = "warning"

    return {
        "student_id": student_id,
        "status": final_status,
        "timeline_validation": timeline_validation,
        "cross_list_violations": cross_list_violations,
        "credit_summary": {
            "total_earned": earned_credits,
            "total_planned": planned_credits,
            "total_remaining_for_graduation": max(0, 120 - earned_credits - planned_credits)
        }
    }