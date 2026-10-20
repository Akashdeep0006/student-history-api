from fastapi import FastAPI, UploadFile, File, HTTPException, status
from pydantic import BaseModel
from typing import List
from bs4 import BeautifulSoup

app = FastAPI()

# In-memory database isolated per student
# Format: {"student_id": {"history": [], "plan": []}}
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

# --- Helper Function for HTML Parsing ---
def parse_transcript_html(html_content: bytes) -> List[dict]:
    soup = BeautifulSoup(html_content, 'html.parser')
    extracted_courses = {}

    for table in soup.find_all('table'):
        rows = table.find_all('tr')
        if not rows:
            continue
        
        # Identify column indices from the header row
        headers = [th.get_text(strip=True).lower() for th in rows[0].find_all(['th', 'td'])]
        
        col_idx = {}
        for i, header_text in enumerate(headers):
            if 'status' in header_text: col_idx['status'] = i
            elif 'course' in header_text: col_idx['course'] = i
            elif 'grade' in header_text: col_idx['grade'] = i
            elif 'term' in header_text: col_idx['term'] = i
            elif 'credits' in header_text: col_idx['credits'] = i
            
        # Ensure this is a valid transcript table
        if len(col_idx) < 5:
            continue
            
        for row in rows[1:]:
            cells = row.find_all(['td', 'th'])
            if len(cells) <= max(col_idx.values()):
                continue
                
            status_val = cells[col_idx['status']].get_text(strip=True)
            term_val = cells[col_idx['term']].get_text(strip=True)
            
            # Canonical Rule 1 & 2
            if status_val not in ['Completed', 'In-Progress', 'Attempted']:
                continue
            if not term_val:
                continue
                
            course_val = cells[col_idx['course']].get_text(strip=True)
            grade_val = cells[col_idx['grade']].get_text(strip=True)
            credits_str = cells[col_idx['credits']].get_text(strip=True)
            
            try:
                credits_val = int(credits_str)
            except ValueError:
                credits_val = 0
                
            # Grade ranking for deduplication
            try:
                float(grade_val)
                grade_score = 3 # Numeric beats all
            except ValueError:
                if grade_val and grade_val.upper() != 'P':
                    grade_score = 2 # Letter beats P/blank
                else:
                    grade_score = 1 # P or blank is lowest
                    
            record_key = (course_val, term_val)
            current_rank = (grade_score, credits_val)
            
            # Deduplicate by keeping the highest rank
            if record_key not in extracted_courses or current_rank > extracted_courses[record_key][0]:
                extracted_courses[record_key] = (current_rank, {
                    "course_code": course_val,
                    "term": term_val,
                    "credits_earned": credits_val,
                    "status": status_val
                })
                
    return [v[1] for v in extracted_courses.values()]

# --- History Endpoints ---
@app.post("/api/v1/students/{student_id}/history/import", status_code=status.HTTP_201_CREATED)
async def import_history(student_id: str, file: UploadFile = File(...)):
    contents = await file.read()
    parsed_history = parse_transcript_html(contents)
    
    if student_id not in db:
        db[student_id] = {"history": [], "plan": []}
        
    db[student_id]["history"] = parsed_history
    return {"status": "success", "past_courses_imported": len(parsed_history)}

@app.put("/api/v1/students/{student_id}/history")
def update_history(student_id: str, payload: HistoryUpdate):
    if student_id not in db:
        raise HTTPException(status_code=404, detail="Student not found")
    
    # Convert Pydantic models back to dicts for internal storage
    db[student_id]["history"] = [item.dict() for item in payload.history]
    return {"status": "success", "message": "Academic history updated successfully"}

@app.delete("/api/v1/students/{student_id}/history")
def delete_history(student_id: str):
    if student_id not in db:
        raise HTTPException(status_code=404, detail="Student not found")
    
    db[student_id]["history"] = []
    return {"status": "success", "message": "Academic history cleared"}

# --- Plan Endpoints ---
@app.post("/api/v1/students/{student_id}/plan")
def create_plan(student_id: str, payload: PlanUpdate):
    if student_id not in db:
        raise HTTPException(status_code=404, detail="Student not found")
        
    db[student_id]["plan"] = [item.dict() for item in payload.planned_courses]
    return {"status": "success", "planned_courses_saved": len(payload.planned_courses)}

@app.put("/api/v1/students/{student_id}/plan")
def update_plan(student_id: str, payload: PlanUpdate):
    if student_id not in db:
        raise HTTPException(status_code=404, detail="Student not found")
        
    db[student_id]["plan"] = [item.dict() for item in payload.planned_courses]
    return {"status": "success", "planned_courses_saved": len(payload.planned_courses)}

@app.delete("/api/v1/students/{student_id}/plan")
def delete_plan(student_id: str):
    if student_id not in db:
        raise HTTPException(status_code=404, detail="Student not found")
        
    db[student_id]["plan"] = []
    return {"status": "success", "message": "Plan cleared"}

# --- Profile Endpoint ---
@app.get("/api/v1/students/{student_id}/profile", response_model=StudentProfile)
def get_profile(student_id: str):
    if student_id not in db:
        raise HTTPException(status_code=404, detail="Student not found")
        
    return {
        "student_id": student_id,
        "history": db[student_id]["history"],
        "plan": db[student_id]["plan"]
    }