# 🚀 HOPPER-MAIN Setup Guide

Complete setup instructions for Instagram lead automation with 12 AI keys.

---

## 📋 Prerequisites

1. **Python 3.10+** installed
2. **20 Gmail accounts** with App Passwords enabled
3. **12 AI API keys** (4 Gemini + 4 OpenRouter + 4 DeepSeek)
4. **Google Sheets API** credentials
5. **Meta Developer** account for Instagram API
6. **Discord Bot** (optional, for email sending)

---

## ⚙️ Step 1: Install Dependencies

```bash
pip install discord.py python-dotenv gspread google-auth pandas tenacity google-generativeai openai
```

---

## 🔑 Step 2: Get API Keys

### **2.1 Gemini API Keys (Get 12 keys)**

1. Go to https://makersuite.google.com/app/apikey
2. Create 12 separate API keys
3. Save them as:
   - `GEMINI_API_KEY_1` through `GEMINI_API_KEY_12`

**Rate Limits:**
- 60 requests/minute per key
- 1,500 requests/day per key
- **Total capacity: 18,000 requests/day**

---

### **2.2 OpenRouter API Keys (Get 12 keys)**

1. Go to https://openrouter.ai/keys
2. Create 12 separate API keys
3. Save them as:
   - `OPENROUTER_API_KEY_1` through `OPENROUTER_API_KEY_12`

**Rate Limits:**
- 20 requests/minute per key
- 500 requests/day per key
- **Total capacity: 6,000 requests/day**

---

### **2.3 DeepSeek API Keys (Get 12 keys)**

1. Go to https://platform.deepseek.com/api_keys
2. Create 12 separate API keys
3. Save them as:
   - `DEEPSEEK_API_KEY_1` through `DEEPSEEK_API_KEY_12`

**Rate Limits:**
- 30 requests/minute per key
- 1,000 requests/day per key
- **Total capacity: 12,000 requests/day**

---

### **2.4 Gmail App Passwords (20 accounts)**

For each Gmail account:

1. Go to https://myaccount.google.com/apppasswords
2. Create an App Password
3. Save as:
   - `EMAIL_ADDRESS_1` / `EMAIL_PASSWORD_1`
   - `EMAIL_ADDRESS_2` / `EMAIL_PASSWORD_2`
   - ... through ...
   - `EMAIL_ADDRESS_20` / `EMAIL_PASSWORD_20`

**Rate Limits:**
- 500 emails/day per account (Google's soft limit)
- **We use 400/day per account to stay safe**
- **Total capacity: 8,000 emails/day**

---

### **2.5 Meta Instagram API**

1. Go to https://developers.facebook.com
2. Create an app with Instagram Graph API
3. Get:
   - `META_TOKEN` (Page Access Token)
   - `META_PAGE_ID` (Facebook Page ID)
   - `META_APP_ID` (App ID)
   - `META_APP_SECRET` (App Secret)

**Rate Limits:**
- 200 calls/hour (Instagram Basic Display)
- **We limit to 500 profiles/day**

---

### **2.6 Google Sheets API**

1. Go to https://console.cloud.google.com
2. Create a Service Account
3. Download JSON credentials
4. Extract these values:
   - `GOOGLE_SHEETS_TYPE`
   - `GOOGLE_SHEETS_PROJECT_ID`
   - `GOOGLE_SHEETS_PRIVATE_KEY_ID`
   - `GOOGLE_SHEETS_PRIVATE_KEY`
   - `GOOGLE_SHEETS_CLIENT_EMAIL`
   - `GOOGLE_SHEETS_CLIENT_ID`
   - `GOOGLE_SHEETS_CLIENT_X509_CERT_URL`

5. Share your spreadsheet with the service account email

---

## 📝 Step 3: Configure .env File

Copy `.env.example` to `.env`:

```bash
cp .env.example .env
```

Fill in ALL values (36+ API keys total).

---

## 📊 Step 4: Setup Google Sheets

Create a Google Sheet with these tabs:

### **Tab 1: Leads**
Columns:
- Email
- Link

Example:
```
user@example.com | https://instagram.com/username
```

### **Tab 2: Day1Queue** (Auto-created by scraper)
This will be auto-populated with 26 columns when you run the scraper.

---

## 🎯 Step 5: Usage

### **PHASE 1: Scraping (Terminal)**

```bash
python scrapper.py
```

**Select:**
- Mode: `1` (Scraper)
- AI Style: `1` (Gemini preferred)

**What happens:**
- Reads "Leads" sheet
- Scrapes Instagram profiles (500/day max)
- Generates AI emails using 12 keys with auto-rotation
- Writes to Day1Queue
- Deletes from Leads

**Output:**
```
✅ Scraping completed! 500 profiles processed into Day1Queue
📊 Remaining profiles today: 0/500
🤖 Healthy AI keys: 12/12
```

---

### **PHASE 2: Email Sending (Discord Bot)**

```bash
python main.py
```

**In Discord:**
```
/send queue:Day1Queue count:500 type:initial
```

**What happens:**
- Bot reads Day1Queue
- Sends 500 emails using 20 Gmail accounts (rotation)
- Updates sheet:
  - EmailStatus → "Sent"
  - EmailDate → timestamp
  - EmailId → message ID
  - SenderEmail → account used

---

### **PHASE 3: Follow-up Generation (Terminal - Day 4)**

```bash
python scrapper.py
```

**Select:**
- Mode: `2` (Follow-up)
- Sheet: `Day1Queue`
- Follow-up: `1` (FollowUp1)

**What happens:**
- Finds contacts where ReplyStatus = "Pending"
- AI generates follow-up email
- Updates FollowUp1 column

---

### **PHASE 4: Send Follow-up (Discord - Day 4)**

```
/send queue:Day1Queue count:300 type:followup1
```

**What happens:**
- Filters where FollowUp1Status = "Pending"
- Sends as reply (uses EmailId for threading)
- Updates FollowUp1Status → "Sent"

---

## 📈 Monitoring

### **Check AI Key Status**

```bash
python -c "from utils.Ai import get_ai_status; import json; print(json.dumps(get_ai_status(), indent=2))"
```

### **Check Rate Limits**

```bash
python -c "from utils.rate_limiter import get_rate_limit_status; import json; print(json.dumps(get_rate_limit_status(), indent=2))"
```

### **Check Email Status (Discord)**

```
/emailstatus queue:Day1Queue
```

---

## 📂 Log Files

All logs are saved in `/logs/`:

- `scraper.log` - Main scraper activity
- `ai_keys.log` - AI key usage and rotation
- `ai_keys_state.json` - AI key health state
- `rate_limiter_state.json` - Daily usage tracking
- `worker.log` - Email worker activity

---

## ⚠️ Important Notes

### **AI Key Management**
- System automatically rotates through all 12 keys per provider
- Exhausted keys are marked and skipped
- State persists across restarts
- **Never manually delete state files during a run**

### **Rate Limits**
- Instagram: 500 profiles/day (hard limit)
- AI: 36,000 total requests/day across all keys
- Gmail: 8,000 emails/day (400 per account)

### **Sheet Structure**
- Never manually edit Day1Queue while scraper is running
- Always backup your sheet before bulk operations
- Max 500 rows per queue sheet (auto-creates new ones)

---

## 🐛 Troubleshooting

### **"All AI keys exhausted"**
- Wait 24 hours for daily limits to reset
- OR add more API keys to your `.env`

### **"Instagram rate limit reached"**
- Wait until next day (resets at midnight)
- Check `rate_limiter_state.json`

### **"Gmail authentication failed"**
- Verify App Passwords are correct (not regular passwords)
- Ensure 2FA is enabled on Gmail accounts

### **"Google Sheets permission denied"**
- Share sheet with service account email
- Check `GOOGLE_