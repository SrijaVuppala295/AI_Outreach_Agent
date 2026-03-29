# utils/Ai.py - OPTIMIZED: Auto-selects available keys, NO user input
import os
import json
import time
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Tuple
from dotenv import load_dotenv
import google.generativeai as genai
from openai import OpenAI
from tenacity import retry, wait_exponential, stop_after_attempt

load_dotenv()

# ======================== LOGGING SETUP ========================
import logging
os.makedirs("logs", exist_ok=True)

ai_logger = logging.getLogger("ai_manager")
ai_logger.setLevel(logging.DEBUG)

if not ai_logger.handlers:
    fh = logging.FileHandler("logs/ai_keys.log", encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    ai_logger.addHandler(fh)
    
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(logging.Formatter("%(asctime)s [AI] %(message)s"))
    ai_logger.addHandler(ch)

# ======================== AI KEY MANAGER ========================
class AIKeyManager:
    """
    OPTIMIZED: Manages 36 API keys with smart auto-selection
    - NO user input required
    - Auto-selects healthiest provider
    - Prevents key exhaustion with intelligent rotation
    """
    
    def __init__(self):
        self.load_api_keys()
        self.state_file = "logs/ai_keys_state.json"
        
        # Conservative rate limits to prevent exhaustion
        self.rate_limits = {
            'gemini': {
                'requests_per_minute': 10,  # Reduced from 15
                'requests_per_day': 450,     # Reduced from 500 (10% buffer)
                'tokens_per_day': 900_000    # Reduced from 1M (10% buffer)
            },
            'openrouter': {
                'requests_per_minute': 15,   # Reduced from 20
                'requests_per_day': 450,     # Reduced from 500 (10% buffer)
                'tokens_per_day': 90_000     # Reduced from 100K (10% buffer)
            },
            'deepseek': {
                'requests_per_minute': 20,   # Reduced from 30
                'requests_per_day': 450,     # Reduced from 500 (10% buffer)
                'tokens_per_day': 450_000    # Reduced from 500K (10% buffer)
            }
        }
        
        # Provider priority (most reliable first)
        self.provider_priority = ['gemini', 'deepseek', 'openrouter']
        
        # State tracking
        self.usage_state = {}
        self.exhausted_keys = set()
        self.error_counts = {}
        self.last_used_provider = None
        
        self.load_state()
        ai_logger.info(f"Initialized AI Manager with {self.total_keys()} total keys")
        ai_logger.info(f"Provider priority: {' → '.join(self.provider_priority)}")
    
    def load_api_keys(self):
        """Load all 36 API keys from environment"""
        self.api_keys = {
            'gemini': [],
            'openrouter': [],
            'deepseek': []
        }
        
        # Load Gemini keys
        for i in range(1, 13):
            key = os.getenv(f'GEMINI_API_KEY_{i}')
            if key:
                self.api_keys['gemini'].append({
                    'id': f'gemini_{i}',
                    'key': key,
                    'provider': 'gemini',
                    'index': i
                })
        
        # Load OpenRouter keys
        for i in range(1, 13):
            key = os.getenv(f'OPENROUTER_API_KEY_{i}')
            if key:
                self.api_keys['openrouter'].append({
                    'id': f'openrouter_{i}',
                    'key': key,
                    'provider': 'openrouter',
                    'index': i
                })
        
        # Load DeepSeek keys
        for i in range(1, 13):
            key = os.getenv(f'DEEPSEEK_API_KEY_{i}')
            if key:
                self.api_keys['deepseek'].append({
                    'id': f'deepseek_{i}',
                    'key': key,
                    'provider': 'deepseek',
                    'index': i
                })
        
        ai_logger.info(f"Loaded keys: Gemini={len(self.api_keys['gemini'])}, "
                      f"OpenRouter={len(self.api_keys['openrouter'])}, "
                      f"DeepSeek={len(self.api_keys['deepseek'])}")
    
    def total_keys(self) -> int:
        return sum(len(keys) for keys in self.api_keys.values())
    
    def load_state(self):
        """Load usage state from disk"""
        try:
            if os.path.exists(self.state_file):
                with open(self.state_file, 'r') as f:
                    data = json.load(f)
                    
                    for key_id, state in data.get('usage', {}).items():
                        self.usage_state[key_id] = {
                            'minute_count': state.get('minute_count', 0),
                            'daily_count': state.get('daily_count', 0),
                            'last_minute_reset': datetime.fromisoformat(state['last_minute_reset']) 
                                if state.get('last_minute_reset') else datetime.now(),
                            'last_daily_reset': datetime.fromisoformat(state['last_daily_reset']).date() 
                                if state.get('last_daily_reset') else datetime.now().date()
                        }
                    
                    self.exhausted_keys = set(data.get('exhausted', []))
                    self.error_counts = data.get('errors', {})
                    self.last_used_provider = data.get('last_used_provider')
                    
                    ai_logger.info(f"Loaded state: {len(self.exhausted_keys)} exhausted keys")
        except Exception as e:
            ai_logger.warning(f"Could not load state: {e}")
    
    def save_state(self):
        """Save usage state to disk"""
        try:
            os.makedirs(os.path.dirname(self.state_file), exist_ok=True)
            
            usage_data = {}
            for key_id, state in self.usage_state.items():
                usage_data[key_id] = {
                    'minute_count': state['minute_count'],
                    'daily_count': state['daily_count'],
                    'last_minute_reset': state['last_minute_reset'].isoformat(),
                    'last_daily_reset': state['last_daily_reset'].isoformat()
                }
            
            data = {
                'usage': usage_data,
                'exhausted': list(self.exhausted_keys),
                'errors': self.error_counts,
                'last_used_provider': self.last_used_provider,
                'updated_at': datetime.now().isoformat()
            }
            
            with open(self.state_file, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            ai_logger.warning(f"Could not save state: {e}")
    
    def reset_if_needed(self, key_id: str, provider: str):
        """Reset counters if time periods have elapsed"""
        if key_id not in self.usage_state:
            self.usage_state[key_id] = {
                'minute_count': 0,
                'daily_count': 0,
                'last_minute_reset': datetime.now(),
                'last_daily_reset': datetime.now().date()
            }
        
        state = self.usage_state[key_id]
        now = datetime.now()
        
        # Reset minute counter
        if (now - state['last_minute_reset']).seconds >= 60:
            state['minute_count'] = 0
            state['last_minute_reset'] = now
            ai_logger.debug(f"{key_id}: Minute counter reset")
        
        # Reset daily counter
        if now.date() > state['last_daily_reset']:
            state['daily_count'] = 0
            state['last_daily_reset'] = now.date()
            
            if key_id in self.exhausted_keys:
                self.exhausted_keys.remove(key_id)
                ai_logger.info(f"{key_id}: Daily limit reset, key re-enabled")
            
            # Clear error counts on daily reset
            if key_id in self.error_counts:
                self.error_counts[key_id] = {}
    
    def is_key_available(self, key_id: str, provider: str) -> Tuple[bool, str]:
        """Check if key is available (not exhausted, within rate limits)"""
        
        if key_id in self.exhausted_keys:
            return False, "exhausted"
        
        self.reset_if_needed(key_id, provider)
        
        state = self.usage_state[key_id]
        limits = self.rate_limits[provider]
        
        # Check minute limit
        if state['minute_count'] >= limits['requests_per_minute']:
            return False, "minute_limit"
        
        # Check daily limit (with 10% buffer to prevent hitting actual limit)
        if state['daily_count'] >= limits['requests_per_day']:
            self.exhausted_keys.add(key_id)
            self.save_state()
            ai_logger.warning(f"⚠️ {key_id} exhausted (daily limit reached: {state['daily_count']}/{limits['requests_per_day']})")
            return False, "daily_limit"
        
        return True, "available"
    
    def get_healthiest_provider(self) -> Optional[str]:
        """
        OPTIMIZED: Returns provider with most available capacity
        NO user input required - fully automatic
        """
        provider_health = {}
        
        for provider in self.provider_priority:
            available_keys = 0
            total_remaining = 0
            
            for key_info in self.api_keys[provider]:
                key_id = key_info['id']
                available, reason = self.is_key_available(key_id, provider)
                
                if available:
                    available_keys += 1
                    state = self.usage_state.get(key_id, {'daily_count': 0})
                    limit = self.rate_limits[provider]['requests_per_day']
                    total_remaining += (limit - state.get('daily_count', 0))
            
            provider_health[provider] = {
                'available_keys': available_keys,
                'total_remaining': total_remaining,
                'health_score': available_keys * 1000 + total_remaining  # Prioritize available keys
            }
            
            ai_logger.debug(f"{provider}: {available_keys} keys, {total_remaining} calls remaining")
        
        # Select provider with best health score
        best_provider = max(provider_health.items(), key=lambda x: x[1]['health_score'])
        
        if best_provider[1]['health_score'] == 0:
            ai_logger.error("🚨 ALL PROVIDERS EXHAUSTED!")
            return None
        
        selected = best_provider[0]
        ai_logger.info(f"📊 Auto-selected provider: {selected.upper()} "
                      f"({provider_health[selected]['available_keys']} keys available)")
        
        return selected
    
    def get_next_available_key(self, preferred_provider: Optional[str] = None) -> Optional[Dict]:
        """
        Get next available API key with intelligent rotation
        If preferred_provider is None, auto-selects healthiest provider
        """
        
        # If no preference, auto-select healthiest provider
        if not preferred_provider:
            preferred_provider = self.get_healthiest_provider()
            if not preferred_provider:
                return None
        
        # Try preferred provider first
        keys = self.api_keys[preferred_provider]
        
        for key_info in keys:
            key_id = key_info['id']
            available, reason = self.is_key_available(key_id, preferred_provider)
            
            if available:
                return key_info
        
        # If preferred provider exhausted, try others in priority order
        ai_logger.warning(f"⚠️ {preferred_provider.upper()} exhausted, trying other providers...")
        
        for provider in self.provider_priority:
            if provider == preferred_provider:
                continue
            
            keys = self.api_keys[provider]
            for key_info in keys:
                key_id = key_info['id']
                available, reason = self.is_key_available(key_id, provider)
                
                if available:
                    ai_logger.info(f"✅ Fallback to {provider.upper()}")
                    return key_info
        
        ai_logger.error("🚨 ALL API KEYS EXHAUSTED OR RATE LIMITED")
        return None
    
    def increment_usage(self, key_id: str, provider: str):
        """Increment usage counters"""
        if key_id not in self.usage_state:
            self.reset_if_needed(key_id, provider)
        
        state = self.usage_state[key_id]
        state['minute_count'] += 1
        state['daily_count'] += 1
        
        # Log usage percentage
        limit = self.rate_limits[provider]['requests_per_day']
        usage_pct = (state['daily_count'] / limit) * 100
        
        if usage_pct >= 90:
            ai_logger.warning(f"⚠️ {key_id} at {usage_pct:.1f}% capacity ({state['daily_count']}/{limit})")
        elif usage_pct >= 80:
            ai_logger.info(f"📊 {key_id} at {usage_pct:.1f}% capacity ({state['daily_count']}/{limit})")
        
        self.save_state()
    
    def record_error(self, key_id: str, error_type: str):
        """Record API error"""
        if key_id not in self.error_counts:
            self.error_counts[key_id] = {}
        
        if error_type not in self.error_counts[key_id]:
            self.error_counts[key_id][error_type] = 0
        
        self.error_counts[key_id][error_type] += 1
        
        total_errors = sum(self.error_counts[key_id].values())
        if total_errors >= 10:  # Reduced from 5 to be more conservative
            self.exhausted_keys.add(key_id)
            ai_logger.warning(f"⚠️ {key_id} temporarily disabled (errors: {total_errors})")
        
        self.save_state()
    
    def generate_with_smart_rotation(self, prompt: str, preferred_provider: Optional[str] = None) -> Optional[str]:
        """
        OPTIMIZED: Generate content with smart rotation
        NO user input - automatically selects best available provider
        """
        
        max_attempts = 5  # Increased from 3 for better resilience
        
        for attempt in range(max_attempts):
            # Auto-select provider if not specified
            key_info = self.get_next_available_key(preferred_provider)
            
            if not key_info:
                ai_logger.error(f"❌ No API keys available (attempt {attempt + 1}/{max_attempts})")
                
                # Wait for rate limits to reset
                if attempt < max_attempts - 1:
                    wait_time = 60  # Wait 1 minute for rate limits
                    ai_logger.info(f"⏳ Waiting {wait_time}s for rate limits to reset...")
                    time.sleep(wait_time)
                    continue
                else:
                    ai_logger.error("🚨 ALL ATTEMPTS EXHAUSTED - NO KEYS AVAILABLE")
                    return None
            
            key_id = key_info['id']
            provider = key_info['provider']
            api_key = key_info['key']
            
            ai_logger.info(f"🤖 Using {key_id} (attempt {attempt + 1}/{max_attempts})")
            
            try:
                # Generate based on provider
                if provider == 'gemini':
                    result = self._generate_gemini(api_key, prompt)
                elif provider == 'openrouter':
                    result = self._generate_openrouter(api_key, prompt)
                elif provider == 'deepseek':
                    result = self._generate_deepseek(api_key, prompt)
                else:
                    ai_logger.error(f"❌ Unknown provider: {provider}")
                    continue
                
                if result:
                    self.increment_usage(key_id, provider)
                    self.last_used_provider = provider
                    self.save_state()
                    ai_logger.info(f"✅ Success with {key_id}")
                    return result
                
            except Exception as e:
                error_msg = str(e).lower()
                
                # Check for quota/rate limit errors
                if any(x in error_msg for x in ['quota', 'rate limit', '429', 'exhausted', 
                                                 'too many requests', 'resource_exhausted']):
                    ai_logger.warning(f"⚠️ Rate limit hit on {key_id}: {e}")
                    self.exhausted_keys.add(key_id)
                    self.record_error(key_id, 'rate_limit')
                    # Don't count this as an attempt, try next key immediately
                    continue
                
                # Other errors
                ai_logger.error(f"❌ Error with {key_id}: {e}")
                self.record_error(key_id, 'api_error')
                
                if attempt == max_attempts - 1:
                    ai_logger.error(f"🚨 All attempts failed for prompt")
                    return None
                
                # Exponential backoff
                wait_time = 2 ** attempt
                ai_logger.info(f"⏳ Waiting {wait_time}s before retry...")
                time.sleep(wait_time)
        
        return None
    
    def _generate_gemini(self, api_key: str, prompt: str) -> str:
        """Generate with Gemini"""
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-2.5-flash-lite')
        
        response = model.generate_content(
            prompt,
            generation_config=genai.types.GenerationConfig(
                temperature=0.7,
                top_p=0.9,
                top_k=40,
                max_output_tokens=2048
            )
        )
        
        if not response.candidates:
            raise Exception("No candidates in Gemini response")
        
        return response.text
    
    def _generate_openrouter(self, api_key: str, prompt: str) -> str:
        """Generate with OpenRouter"""
        client = OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=api_key
        )
        
        response = client.chat.completions.create(
            model="deepseek/deepseek-r1-0528:free",
            messages=[{"role": "user", "content": prompt}],
            extra_headers={
                "HTTP-Referer": "sharkedge.media",
                "X-Title": "Shark Edge Studio"
            }
        )
        
        return response.choices[0].message.content
    
    def _generate_deepseek(self, api_key: str, prompt: str) -> str:
        """Generate with DeepSeek"""
        client = OpenAI(
            base_url="https://api.deepseek.com/v1",
            api_key=api_key
        )
        
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "user", "content": prompt}]
        )
        
        return response.choices[0].message.content
    
    def get_status_report(self) -> Dict:
        """Get detailed status report"""
        report = {
            'total_keys': self.total_keys(),
            'exhausted': len(self.exhausted_keys),
            'healthy': 0,
            'providers': {},
            'keys': {},
            'warnings': []
        }
        
        for provider, keys in self.api_keys.items():
            healthy_count = 0
            total_used = 0
            total_remaining = 0
            
            for key_info in keys:
                key_id = key_info['id']
                
                available, reason = self.is_key_available(key_id, provider)
                if available:
                    healthy_count += 1
                
                state = self.usage_state.get(key_id, {})
                limits = self.rate_limits[provider]
                
                daily_used = state.get('daily_count', 0)
                daily_limit = limits['requests_per_day']
                remaining = daily_limit - daily_used
                usage_pct = (daily_used / daily_limit * 100) if daily_limit > 0 else 0
                
                total_used += daily_used
                total_remaining += remaining
                
                # Add warnings for high usage
                if usage_pct >= 90:
                    report['warnings'].append(f"{key_id} at {usage_pct:.0f}% ({daily_used}/{daily_limit})")
                
                report['keys'][key_id] = {
                    'provider': provider,
                    'daily_used': daily_used,
                    'daily_limit': daily_limit,
                    'remaining': remaining,
                    'usage_pct': round(usage_pct, 1),
                    'minute_used': state.get('minute_count', 0),
                    'minute_limit': limits['requests_per_minute'],
                    'status': 'exhausted' if key_id in self.exhausted_keys else 'healthy',
                    'errors': self.error_counts.get(key_id, {})
                }
            
            report['providers'][provider] = {
                'total': len(keys),
                'healthy': healthy_count,
                'exhausted': len(keys) - healthy_count,
                'total_used': total_used,
                'total_limit': limits['requests_per_day'] * len(keys),
                'total_remaining': total_remaining,
                'usage_pct': round((total_used / (limits['requests_per_day'] * len(keys)) * 100), 1) if len(keys) > 0 else 0
            }
            report['healthy'] += healthy_count
        
        return report

# ======================== GLOBAL INSTANCE ========================
ai_manager = AIKeyManager()

# ======================== PUBLIC API ========================
def generate_email(data: str, run_style: int = None) -> str:
    """
    Generate professional email with proper formatting
    
    Args:
        data: Prompt data
        run_style: IGNORED - system auto-selects best provider
    
    Returns:
        Formatted email
    """
    
    # Load prompt template
    try:
        config_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            'resources',
            'prompt.txt'
        )
        with open(config_path, 'r', encoding='UTF-8') as f:
            content = f.read()
    except Exception as e:
        ai_logger.warning(f"Could not read prompt.txt: {e}")
        content = "Generate a professional cold email:"
    
    # Main generation prompt
    prompt = content + f"\n\n** Data on user:\n{data}\n\nIMPORTANT: Generate ONLY the email body content. DO NOT include greetings like 'Hi/Hello' or signatures like 'Best regards'. These will be added automatically."
    
    # OPTIMIZED: Auto-select provider (NO user input)
    result = ai_manager.generate_with_smart_rotation(prompt, preferred_provider=None)
    
    if not result:
        ai_logger.error("AI generation failed, using fallback")
        return "Subject: Partnership Opportunity\n\nI noticed your impressive content and would love to discuss how we can help scale your reach and engagement. We specialize in creator growth strategies that deliver real results.\n\nWould you be open to a brief conversation?"
    
    # Format email properly
    parse_prompt = '''You are a professional email formatter. Your job is to format raw email content into a clean structure.

CRITICAL RULES:
1. Output format MUST be:
   Subject: [subject line here]
   
   [body content ONLY - no greeting, no signature]

2. DO NOT include:
   - Greetings (Hi, Hello, Hey, Dear)
   - Signatures (Best regards, Sincerely, etc.)
   - Company names or sender names
   - Any placeholders like [Your Name], [Company]

3. The body should be 3-5 paragraphs:
   - Opening: Reference their specific content/work
   - Value: What you noticed/appreciate
   - Offer: How you can help
   - CTA: Soft call-to-action

4. Keep it professional but conversational
5. No markdown, no formatting, just plain text
6. Subject line should be personalized and relevant

Format this email content:
{}
'''
    
    formatted = ai_manager.generate_with_smart_rotation(parse_prompt.format(result), preferred_provider=None)
    
    if not formatted:
        return "Subject: Impressed by Your Content\n\nI've been following your work and I'm impressed by your approach to engaging your audience. Your recent content particularly stands out for its authenticity and impact.\n\nWe help creators scale their reach while maintaining that authentic connection. We've helped similar creators increase engagement by 3-5x.\n\nWould you be interested in a brief conversation about your growth goals?"
    
    return formatted

def generate_followup_email(original_email: str, profile_data: str, run_style: int = None, is_breakup: bool = False) -> str:
    """
    Generate follow-up email
    
    Args:
        run_style: IGNORED - system auto-selects best provider
        is_breakup: If True, generates a "breakup" email (final follow-up)
    """
    
    if is_breakup:
        prompt = f'''Generate a "breakup" email (final follow-up).

ORIGINAL EMAIL SENT:
{original_email}

PROFILE CONTEXT:
{profile_data}

Requirements:
1. Acknowledge this is the LAST email you will send
2. Be polite and professional ("I don't want to clutter your inbox")
3. Leave the door open for future ("If timing changes...")
4. VERY SHORT (50-80 words)
5. Softest possible CTA
6. NO desperation, guilt-tripping, or "did you see my last email"

IMPORTANT: Generate ONLY the body content. NO greetings, NO signatures.
'''
    else:
        prompt = f'''Generate a brief follow-up email.

ORIGINAL EMAIL SENT:
{original_email}

PROFILE CONTEXT:
{profile_data}

Requirements:
1. Reference original email briefly (don't copy it)
2. Add NEW value or insight
3. Keep it VERY SHORT (60-100 words)
4. Soft, friendly CTA
5. Not pushy or desperate
6. Human and conversational

IMPORTANT: Generate ONLY the body content. NO greetings, NO signatures.
'''
    
    result = ai_manager.generate_with_smart_rotation(prompt, preferred_provider=None)
    
    if not result:
        if is_breakup:
            return "Subject: Re: Last try?\n\nI assume you're busy or not interested right now, so this will be my last email to avoid cluttering your inbox.\n\nIf you ever need help scaling your content in the future, I'm always around.\n\nBest of luck with everything!"
        return "Subject: Re: Following Up\n\nJust wanted to circle back on my previous message. I've been thinking about ways we could help amplify your content strategy.\n\nNo pressure at all - just wanted to keep the conversation open if you're interested."
    
    parse_prompt = '''Format this follow-up email:

RULES:
1. Format: 
   Subject: Re: [topic]
   
   [body - no greeting, no signature]

2. Subject should be "Re:" format for thread continuity
3. Body should be 2-3 short sentences
4. NO greetings or signatures

Format this:
{}
'''
    
    formatted = ai_manager.generate_with_smart_rotation(parse_prompt.format(result), preferred_provider=None)
    
    return formatted if formatted else result

def get_ai_status() -> Dict:
    """Get AI manager status"""
    return ai_manager.get_status_report()

# Backward compatibility - deprecated
def get_ai_style():
    """DEPRECATED: System now auto-selects provider"""
    print("🤖 AI Auto-Selection Enabled")
    print("   System automatically selects healthiest provider")
    print("   No manual selection needed!")
    return "auto"

