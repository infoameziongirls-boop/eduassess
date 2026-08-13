# EduAssess External Results Entry System Integration Guide

## Overview
This guide explains how to connect an external results entry platform to EduAssess, allowing results entered on a third-party system to be automatically synchronized with the EduAssess database.

---

## Table of Contents
1. [Architecture Overview](#architecture-overview)
2. [API Endpoints for Results Import](#api-endpoints-for-results-import)
3. [Data Schema & Validation](#data-schema--validation)
4. [Implementation Examples](#implementation-examples)
5. [Security & Authentication](#security--authentication)
6. [Error Handling & Logging](#error-handling--logging)
7. [Testing Guide](#testing-guide)

---

## Architecture Overview

### System Components

```
External Results Platform (e.g., Google Forms, Custom App)
           ↓
      HTTP/REST API Calls
           ↓
    EduAssess API Gateway
           ↓
    Authentication & Validation Layer
           ↓
    Assessment Database (SQLAlchemy)
           ↓
    Student Records Updated
           ↓
    Results Released (if configured)
```

### Data Flow

1. **External System** collects results (teacher entry point)
2. **Sends POST request** to EduAssess API with assessment data
3. **EduAssess validates** the data structure and authentication
4. **Creates Assessment record** in the database
5. **Logs the action** in ActivityLog
6. **Returns response** with success/error status

---

## API Endpoints for Results Import

### 1. **Create Single Assessment**

**Endpoint:** `POST /api/v1/assessments/create`

**Authentication:** 
- API Key-based authentication required
- OR Bearer token from authenticated user

**Request Headers:**
```http
POST /api/v1/assessments/create HTTP/1.1
Host: eduassess.example.com
Content-Type: application/json
Authorization: Bearer <API_KEY>
```

**Request Body:**
```json
{
  "student_number": "STU001",
  "category": "mid_term",
  "subject": "mathematics",
  "score": 78.5,
  "max_score": 100,
  "term": "term1",
  "academic_year": "2024-2025",
  "session": "First Term",
  "assessor": "Mr. John Smith",
  "comments": "Good progress, needs more practice"
}
```

**Response (201 Created):**
```json
{
  "success": true,
  "message": "Assessment created successfully",
  "assessment_id": 1234,
  "student_id": 567,
  "data": {
    "id": 1234,
    "student_number": "STU001",
    "category": "mid_term",
    "subject": "mathematics",
    "score": 78.5,
    "max_score": 100,
    "percentage": 78.5,
    "grade": "B+",
    "date_recorded": "2024-06-15T10:30:00Z"
  }
}
```

**Error Response (400 Bad Request):**
```json
{
  "success": false,
  "error": "Invalid category",
  "details": "Category must be one of: ica1, ica2, icp1, icp2, gp1, gp2, practical, mid_term, end_term",
  "code": "INVALID_CATEGORY"
}
```

---

### 2. **Bulk Import Assessments**

**Endpoint:** `POST /api/v1/assessments/bulk`

**Authentication:** Required (API Key or Bearer token)

**Request Body:**
```json
{
  "assessments": [
    {
      "student_number": "STU001",
      "category": "ica1",
      "subject": "english_language",
      "score": 42,
      "max_score": 50,
      "term": "term1",
      "academic_year": "2024-2025",
      "session": "First Term",
      "assessor": "Ms. Jane Doe"
    },
    {
      "student_number": "STU002",
      "category": "ica1",
      "subject": "english_language",
      "score": 48,
      "max_score": 50,
      "term": "term1",
      "academic_year": "2024-2025",
      "session": "First Term",
      "assessor": "Ms. Jane Doe"
    }
  ]
}
```

**Response (201 Created):**
```json
{
  "success": true,
  "message": "Bulk import completed",
  "total_records": 2,
  "successful": 2,
  "failed": 0,
  "results": [
    {
      "status": "created",
      "student_number": "STU001",
      "assessment_id": 1234
    },
    {
      "status": "created",
      "student_number": "STU002",
      "assessment_id": 1235
    }
  ]
}
```

---

### 3. **Get Student by Identifier (for validation)**

**Endpoint:** `GET /api/v1/students/lookup?identifier=STU001`

**Authentication:** Required

**Query Parameters:**
- `identifier` (required): Student number or reference number
- `include_assessments` (optional): true/false - include existing assessments

**Response (200 OK):**
```json
{
  "success": true,
  "student": {
    "id": 567,
    "student_number": "STU001",
    "first_name": "John",
    "last_name": "Doe",
    "class": "Form 3A",
    "study_area": "Science",
    "reference_number": "REF001"
  }
}
```

---

### 4. **Validate Assessment Before Submission**

**Endpoint:** `POST /api/v1/assessments/validate`

**Purpose:** Pre-flight check before creating assessment (no database changes)

**Request Body:**
```json
{
  "student_number": "STU001",
  "category": "mid_term",
  "subject": "mathematics",
  "score": 85,
  "max_score": 100
}
```

**Response (200 OK):**
```json
{
  "valid": true,
  "message": "Assessment data is valid",
  "warnings": []
}
```

**Response with Issues (200 OK):**
```json
{
  "valid": false,
  "message": "Assessment data has issues",
  "errors": [
    "Student with number 'STU999' not found"
  ],
  "warnings": [
    "Score exceeds category maximum of 100"
  ]
}
```

---

## Data Schema & Validation

### Assessment Model Fields

| Field | Type | Required | Validation | Notes |
|-------|------|----------|-----------|-------|
| `student_number` | String | ✅ | Unique, 1-50 chars | Primary student identifier |
| `category` | String | ✅ | Enum | Must be in: ica1, ica2, icp1, icp2, gp1, gp2, practical, mid_term, end_term |
| `subject` | String | ✅ | Valid subject key | e.g., mathematics, english_language, biology |
| `score` | Float | ✅ | 0 ≤ score ≤ max_score | Typically 0-100 or 0-50 |
| `max_score` | Float | ✅ | Positive number | Default: 100 |
| `term` | String | ✅ | e.g., "term1", "term2" | Current term setting |
| `academic_year` | String | ✅ | e.g., "2024-2025" | Current academic year |
| `session` | String | ✅ | e.g., "First Term" | Session label |
| `assessor` | String | ❌ | 0-120 chars | Teacher/assessor name |
| `comments` | String | ❌ | 0-500 chars | Optional feedback |
| `class_name` | String | ❌ | Valid class | Overrides student's current class |

### Category Max Scores (Configuration)
```python
CATEGORY_MAX_SCORES = {
    'ica1': 50,
    'ica2': 50,
    'icp1': 50,
    'icp2': 50,
    'gp1': 50,
    'gp2': 50,
    'practical': 100,
    'mid_term': 100,
    'end_term': 100,
}
```

### Assessment Weights (Grade Calculation)
```python
ASSESSMENT_WEIGHTS = {
    'ica1': 0.05,      # 5%
    'ica2': 0.05,      # 5%
    'icp1': 0.05,      # 5%
    'icp2': 0.05,      # 5%
    'gp1': 0.05,       # 5%
    'gp2': 0.05,       # 5%
    'practical': 0.10, # 10%
    'mid_term': 0.10,  # 10%
    'end_term': 0.50,  # 50%
}
```

---

## Implementation Examples

### Example 1: Python Client Using Requests

```python
import requests
import json
from datetime import datetime

class EduAssessClient:
    def __init__(self, base_url, api_key):
        self.base_url = base_url
        self.api_key = api_key
        self.headers = {
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json'
        }
    
    def create_assessment(self, assessment_data):
        """Create a single assessment record"""
        url = f"{self.base_url}/api/v1/assessments/create"
        response = requests.post(url, json=assessment_data, headers=self.headers)
        return response.json()
    
    def bulk_create_assessments(self, assessments_list):
        """Bulk create multiple assessments"""
        url = f"{self.base_url}/api/v1/assessments/bulk"
        payload = {"assessments": assessments_list}
        response = requests.post(url, json=payload, headers=self.headers)
        return response.json()
    
    def lookup_student(self, student_number):
        """Check if student exists and get details"""
        url = f"{self.base_url}/api/v1/students/lookup"
        params = {'identifier': student_number}
        response = requests.get(url, params=params, headers=self.headers)
        return response.json()
    
    def validate_assessment(self, assessment_data):
        """Validate assessment data before submission"""
        url = f"{self.base_url}/api/v1/assessments/validate"
        response = requests.post(url, json=assessment_data, headers=self.headers)
        return response.json()


# Usage Example
if __name__ == '__main__':
    client = EduAssessClient(
        base_url='https://eduassess.example.com',
        api_key='your_api_key_here'
    )
    
    # Single assessment
    assessment = {
        "student_number": "STU001",
        "category": "mid_term",
        "subject": "mathematics",
        "score": 78.5,
        "max_score": 100,
        "term": "term1",
        "academic_year": "2024-2025",
        "session": "First Term",
        "assessor": "Mr. John Smith"
    }
    
    # Validate first
    validation = client.validate_assessment(assessment)
    if validation['valid']:
        # Create if valid
        result = client.create_assessment(assessment)
        print(f"Created: {result}")
    else:
        print(f"Validation failed: {validation['errors']}")
```

### Example 2: Google Apps Script Integration

```javascript
// Google Sheets Script for EduAssess Integration

const EDUASSESS_API = 'https://eduassess.example.com/api/v1';
const API_KEY = 'your_api_key_here';

function submitResultsToEduAssess() {
  const sheet = SpreadsheetApp.getActiveSheet();
  const data = sheet.getDataRange().getValues();
  
  // Skip header row
  const assessments = [];
  for (let i = 1; i < data.length; i++) {
    const row = data[i];
    
    // Map columns: A=Student#, B=Category, C=Subject, D=Score, E=Max
    const assessment = {
      student_number: row[0],
      category: row[1],
      subject: row[2],
      score: parseFloat(row[3]),
      max_score: parseFloat(row[4]),
      term: "term1",
      academic_year: "2024-2025",
      session: "First Term",
      assessor: Session.getUser().getEmail()
    };
    
    assessments.push(assessment);
  }
  
  // Send to EduAssess
  const options = {
    method: 'post',
    headers: {
      'Authorization': `Bearer ${API_KEY}`,
      'Content-Type': 'application/json'
    },
    payload: JSON.stringify({ assessments: assessments }),
    muteHttpExceptions: true
  };
  
  const response = UrlFetchApp.fetch(`${EDUASSESS_API}/assessments/bulk`, options);
  const result = JSON.parse(response.getContentText());
  
  if (result.success) {
    SpreadsheetApp.getUi().alert(`✅ Success: ${result.successful} records imported`);
  } else {
    SpreadsheetApp.getUi().alert(`❌ Error: ${result.message}`);
  }
}

function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu('EduAssess')
    .addItem('Submit Results to EduAssess', 'submitResultsToEduAssess')
    .addToUi();
}
```

### Example 3: JavaScript/Node.js Express Middleware

```javascript
// Express middleware for EduAssess integration

const axios = require('axios');

const eduAssessConfig = {
  baseURL: process.env.EDUASSESS_URL || 'https://eduassess.example.com',
  apiKey: process.env.EDUASSESS_API_KEY,
  timeout: 5000
};

// Create axios instance with default headers
const eduAssessClient = axios.create({
  baseURL: `${eduAssessConfig.baseURL}/api/v1`,
  headers: {
    'Authorization': `Bearer ${eduAssessConfig.apiKey}`,
    'Content-Type': 'application/json'
  }
});

// Express route for receiving results from external platform
app.post('/receive-results', async (req, res) => {
  try {
    const { assessments } = req.body;
    
    // Validate payload
    if (!Array.isArray(assessments) || assessments.length === 0) {
      return res.status(400).json({
        error: 'Invalid payload: assessments array required'
      });
    }
    
    // Validate each assessment before bulk submit
    const validationResults = [];
    for (const assessment of assessments) {
      try {
        const validation = await eduAssessClient.post('/assessments/validate', assessment);
        validationResults.push({
          student: assessment.student_number,
          valid: validation.data.valid
        });
      } catch (error) {
        console.error(`Validation error for ${assessment.student_number}:`, error.message);
      }
    }
    
    // Bulk submit valid assessments
    const response = await eduAssessClient.post('/assessments/bulk', {
      assessments: assessments
    });
    
    // Log the import
    console.log(`Imported ${response.data.successful} assessments from external platform`);
    
    // Return results
    res.json({
      success: true,
      message: response.data.message,
      imported: response.data.successful,
      failed: response.data.failed
    });
    
  } catch (error) {
    console.error('Error processing results:', error.message);
    res.status(500).json({
      error: 'Failed to import results',
      details: error.message
    });
  }
});
```

---

## Security & Authentication

### 1. API Key Authentication

**Setup in EduAssess:**

```python
# models.py - Add to API Key model
class APIKey(db.Model):
    __tablename__ = 'api_keys'
    
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(255), unique=True, nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    description = db.Column(db.String(255), nullable=True)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=utcnow)
    last_used = db.Column(db.DateTime, nullable=True)
    
    user = db.relationship('User', backref='api_keys')
```

**Middleware to validate API key:**

```python
# api_v1.py
from flask import request, jsonify
from functools import wraps
from models import APIKey

def api_key_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        auth_header = request.headers.get('Authorization', '')
        
        # Extract token from "Bearer <token>"
        if not auth_header.startswith('Bearer '):
            return jsonify({'error': 'Missing or invalid Authorization header'}), 401
        
        token = auth_header[7:]  # Remove 'Bearer '
        
        # Validate token
        api_key = APIKey.query.filter_by(key=token, is_active=True).first()
        if not api_key:
            return jsonify({'error': 'Invalid API key'}), 401
        
        # Update last_used timestamp
        api_key.last_used = utcnow()
        db.session.commit()
        
        # Set current_user context for logging
        request.api_user = api_key.user
        
        return f(*args, **kwargs)
    return decorated_function
```

### 2. Rate Limiting

```python
# app.py
from flask_limiter import Limiter

limiter = Limiter(
    app=app,
    key_func=lambda: request.headers.get('Authorization', 'anon'),
    default_limits=['1000 per day', '100 per hour'],
    storage_uri='redis://localhost:6379'
)

# Apply to API routes
@api_bp.route('/assessments/bulk')
@limiter.limit('50 per hour')
@api_key_required
def bulk_create_assessments():
    # Implementation
    pass
```

### 3. HTTPS/TLS Requirements

All API calls must use HTTPS in production:

```nginx
# Nginx configuration
server {
    listen 443 ssl http2;
    server_name eduassess.example.com;
    
    ssl_certificate /path/to/cert.pem;
    ssl_certificate_key /path/to/key.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    
    location /api/v1/ {
        proxy_pass http://eduassess_app;
        proxy_set_header X-Forwarded-Proto https;
    }
}
```

---

## Error Handling & Logging

### Error Response Format

```json
{
  "success": false,
  "error": "Validation failed",
  "code": "VALIDATION_ERROR",
  "details": {
    "field": "score",
    "message": "Score must be numeric"
  },
  "timestamp": "2024-06-15T10:30:00Z"
}
```

### Error Codes

| Code | Status | Description |
|------|--------|-------------|
| `INVALID_STUDENT` | 400 | Student number not found |
| `INVALID_CATEGORY` | 400 | Category not in allowed list |
| `INVALID_SUBJECT` | 400 | Subject not recognized |
| `INVALID_SCORE` | 400 | Score validation failed |
| `DUPLICATE_ASSESSMENT` | 409 | Assessment already exists for this student/category/term |
| `UNAUTHORIZED` | 401 | Invalid or missing API key |
| `RATE_LIMITED` | 429 | Too many requests |
| `INTERNAL_ERROR` | 500 | Server error |

### Activity Logging

Every assessment creation is logged:

```python
# Log entry example
ActivityLog(
    user_id=api_user.id,
    action='import_assessment_via_api',
    details=f'Imported {student_number} - {category} ({score}/{max_score})',
    ip_address=request.remote_addr
)
```

---

## Testing Guide

### Test Case 1: Valid Single Assessment

```bash
curl -X POST https://eduassess.example.com/api/v1/assessments/create \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "student_number": "STU001",
    "category": "mid_term",
    "subject": "mathematics",
    "score": 78.5,
    "max_score": 100,
    "term": "term1",
    "academic_year": "2024-2025",
    "session": "First Term",
    "assessor": "Mr. Smith"
  }'
```

### Test Case 2: Bulk Import with Mixed Results

```bash
curl -X POST https://eduassess.example.com/api/v1/assessments/bulk \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "assessments": [
      {"student_number": "STU001", "category": "ica1", "subject": "mathematics", "score": 45, "max_score": 50, "term": "term1", "academic_year": "2024-2025", "session": "First Term"},
      {"student_number": "STU999", "category": "ica1", "subject": "mathematics", "score": 45, "max_score": 50, "term": "term1", "academic_year": "2024-2025", "session": "First Term"}
    ]
  }'
```

### Test Case 3: Validation with Invalid Data

```bash
curl -X POST https://eduassess.example.com/api/v1/assessments/validate \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "student_number": "STU001",
    "category": "invalid_category",
    "subject": "mathematics",
    "score": 150,
    "max_score": 100
  }'
```

---

## Complete Implementation Files

### Step 1: Create Extended API Blueprint

Create `api_v1_extended.py` in your EduAssess project:

```python
# api_v1_extended.py
from flask import Blueprint, request, jsonify
from flask_login import login_required, current_user
from functools import wraps
from models import Student, Assessment, Setting, APIKey
from db import db
from datetime import datetime, timezone

api_bp = Blueprint('api_v1_extended', __name__, url_prefix='/api/v1')

def utcnow():
    return datetime.now(timezone.utc)

# API Key Authentication
def api_key_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        auth_header = request.headers.get('Authorization', '')
        
        if not auth_header.startswith('Bearer '):
            return jsonify({'error': 'Missing or invalid Authorization header'}), 401
        
        token = auth_header[7:]
        api_key = APIKey.query.filter_by(key=token, is_active=True).first()
        
        if not api_key:
            return jsonify({'error': 'Invalid API key'}), 401
        
        api_key.last_used = utcnow()
        db.session.commit()
        request.api_user = api_key.user
        
        return f(*args, **kwargs)
    return decorated_function

# Routes
@api_bp.route('/students/lookup')
@api_key_required
def student_lookup():
    """Lookup student by number or reference"""
    identifier = request.args.get('identifier', '').strip()
    
    if not identifier:
        return jsonify({'error': 'identifier parameter required'}), 400
    
    student = Student.query.filter(
        db.or_(
            Student.student_number == identifier,
            Student.reference_number == identifier
        )
    ).first()
    
    if not student:
        return jsonify({'success': False, 'error': 'Student not found'}), 404
    
    return jsonify({
        'success': True,
        'student': {
            'id': student.id,
            'student_number': student.student_number,
            'first_name': student.first_name,
            'last_name': student.last_name,
            'class': student.get_class_display(),
            'study_area': student.get_study_area_display(),
            'reference_number': student.reference_number
        }
    })

@api_bp.route('/assessments/validate', methods=['POST'])
@api_key_required
def validate_assessment():
    """Pre-flight validation without creating record"""
    data = request.get_json()
    errors = []
    warnings = []
    
    # Required fields
    required = ['student_number', 'category', 'subject', 'score', 'max_score']
    for field in required:
        if field not in data:
            errors.append(f"Missing required field: {field}")
    
    if errors:
        return jsonify({'valid': False, 'errors': errors}), 400
    
    # Validate student
    student = Student.query.filter_by(student_number=data['student_number']).first()
    if not student:
        errors.append(f"Student with number '{data['student_number']}' not found")
    
    # Validate category
    valid_categories = ['ica1', 'ica2', 'icp1', 'icp2', 'gp1', 'gp2', 'practical', 'mid_term', 'end_term']
    if data['category'] not in valid_categories:
        errors.append(f"Invalid category. Must be one of: {', '.join(valid_categories)}")
    
    # Validate score
    try:
        score = float(data['score'])
        max_score = float(data['max_score'])
        
        if score < 0:
            errors.append("Score cannot be negative")
        if max_score <= 0:
            errors.append("Max score must be positive")
        if score > max_score:
            warnings.append(f"Score ({score}) exceeds max score ({max_score})")
    
    except (ValueError, TypeError):
        errors.append("Score and max_score must be numeric")
    
    return jsonify({
        'valid': len(errors) == 0,
        'errors': errors,
        'warnings': warnings
    })

@api_bp.route('/assessments/create', methods=['POST'])
@api_key_required
def create_assessment():
    """Create single assessment"""
    data = request.get_json()
    
    # Validation
    student = Student.query.filter_by(student_number=data.get('student_number')).first()
    if not student:
        return jsonify({
            'success': False,
            'error': 'Invalid student',
            'code': 'INVALID_STUDENT'
        }), 400
    
    # Check duplicate
    existing = Assessment.query.filter_by(
        student_id=student.id,
        category=data['category'],
        subject=data['subject'],
        term=data.get('term'),
        academic_year=data.get('academic_year')
    ).first()
    
    if existing:
        return jsonify({
            'success': False,
            'error': 'Assessment already exists',
            'code': 'DUPLICATE_ASSESSMENT'
        }), 409
    
    # Create assessment
    assessment = Assessment(
        student_id=student.id,
        category=data['category'],
        subject=data['subject'],
        score=float(data['score']),
        max_score=float(data.get('max_score', 100)),
        term=data.get('term'),
        academic_year=data.get('academic_year'),
        session=data.get('session'),
        assessor=data.get('assessor'),
        comments=data.get('comments'),
        teacher_id=request.api_user.id if request.api_user else None
    )
    
    db.session.add(assessment)
    db.session.commit()
    
    return jsonify({
        'success': True,
        'message': 'Assessment created successfully',
        'assessment_id': assessment.id,
        'student_id': student.id,
        'data': {
            'id': assessment.id,
            'student_number': student.student_number,
            'category': assessment.category,
            'subject': assessment.subject,
            'score': assessment.score,
            'max_score': assessment.max_score,
            'percentage': assessment.get_percentage(),
            'grade': assessment.get_grade_letter(),
            'date_recorded': assessment.date_recorded.isoformat()
        }
    }), 201

@api_bp.route('/assessments/bulk', methods=['POST'])
@api_key_required
def bulk_create_assessments():
    """Bulk create multiple assessments"""
    payload = request.get_json()
    assessments_data = payload.get('assessments', [])
    
    if not assessments_data:
        return jsonify({'error': 'assessments array required'}), 400
    
    results = {'successful': 0, 'failed': 0, 'results': []}
    
    for idx, data in enumerate(assessments_data):
        try:
            student = Student.query.filter_by(student_number=data['student_number']).first()
            
            if not student:
                results['results'].append({
                    'index': idx,
                    'status': 'failed',
                    'student_number': data['student_number'],
                    'error': 'Student not found'
                })
                results['failed'] += 1
                continue
            
            # Create assessment
            assessment = Assessment(
                student_id=student.id,
                category=data['category'],
                subject=data['subject'],
                score=float(data['score']),
                max_score=float(data.get('max_score', 100)),
                term=data.get('term'),
                academic_year=data.get('academic_year'),
                session=data.get('session'),
                assessor=data.get('assessor'),
                comments=data.get('comments'),
                teacher_id=request.api_user.id if request.api_user else None
            )
            
            db.session.add(assessment)
            db.session.commit()
            
            results['results'].append({
                'index': idx,
                'status': 'created',
                'student_number': student.student_number,
                'assessment_id': assessment.id
            })
            results['successful'] += 1
        
        except Exception as e:
            results['results'].append({
                'index': idx,
                'status': 'failed',
                'student_number': data.get('student_number', 'unknown'),
                'error': str(e)
            })
            results['failed'] += 1
    
    return jsonify({
        'success': True,
        'message': f'Bulk import completed: {results["successful"]} created, {results["failed"]} failed',
        'total_records': len(assessments_data),
        'successful': results['successful'],
        'failed': results['failed'],
        'results': results['results']
    }), 201
```

### Step 2: Register Blueprint in app.py

```python
# app.py
from api_v1_extended import api_bp as api_bp_extended

app.register_blueprint(api_bp_extended)
```

---

## Best Practices

1. **Always validate before bulk operations** - Use the validate endpoint first
2. **Implement retry logic** - External systems may be temporarily unavailable
3. **Log all imports** - Track data lineage and audit trail
4. **Use pagination** - For large datasets, paginate results
5. **Monitor rate limits** - Implement exponential backoff
6. **Secure API keys** - Use environment variables, rotate regularly
7. **Test in staging first** - Never go straight to production
8. **Document external system changes** - Keep audit logs of all modifications

---

## Troubleshooting

### Common Issues

| Issue | Solution |
|-------|----------|
| 401 Unauthorized | Check API key validity and format (`Bearer <key>`) |
| 404 Student Not Found | Verify student_number matches exactly (case-sensitive) |
| 409 Duplicate Assessment | Check if assessment for this student/category/term already exists |
| 422 Invalid Category | Verify category is in allowed list |
| 500 Internal Error | Check server logs and contact system administrator |

---

## Support & Documentation

For additional help:
- Check `README.md` for general setup
- Review `DOCUMENTATION_INDEX.md` for full API reference
- Submit issues via `/support` ticket system
- Contact system administrator for API key generation

