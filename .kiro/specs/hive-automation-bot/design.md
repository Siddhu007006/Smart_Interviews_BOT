# Technical Design Document: Hive Automation Bot

## Overview

The Hive Automation Bot is a resilient, modular Python application that automates competitive coding problem-solving on Smart Interviews' Hive platform. It combines Playwright-based browser automation with AI-powered code generation and a sophisticated retry mechanism to deliver high success rates across multiple programming languages (C, C++, Java, Python).

The design prioritizes:
- **Resilience**: Five-attempt retry loops with AI-driven debugging
- **Modularity**: Clear separation between browser, auth, Hive UI interaction, AI solving, and state management
- **Incremental Development**: Seven phased rollout from browser setup through batch processing
- **Observability**: Comprehensive logging and state persistence for crash recovery
- **Real Editor Integration**: Programmatic manipulation of actual code editors (Monaco/CodeMirror/Ace), not simple text insertion

---

## Architecture

### System Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                     HIVE AUTOMATION BOT SYSTEM                      │
└─────────────────────────────────────────────────────────────────────┘

                            ┌──────────────────┐
                            │  Configuration   │
                            │   & Secrets      │
                            └────────┬─────────┘
                                     │
┌─────────────┐        ┌────────────▼─────────────┐        ┌──────────────┐
│  Browser    │        │   STATE MANAGER          │        │   Logging &  │
│  Manager    │◄──────►│   (Persistent Storage)   │◄──────►│   Observ.    │
│             │        │                          │        │              │
└─────┬───────┘        └────────────┬─────────────┘        └──────────────┘
      │                             │
      │                    ┌────────▼────────┐
      │                    │  STATE MACHINE  │
      │                    │  Coordinator    │
      │                    └────────┬────────┘
      │                             │
      ├─────────────────────────────┼──────────────────────┬──────────────┐
      │                             │                      │              │
      ▼                             ▼                      ▼              ▼
┌─────────────┐          ┌──────────────────┐    ┌──────────────┐  ┌─────────┐
│  Playwright │          │ Hive Interaction │    │  AI Solver   │  │ Verdict │
│  Browser    │          │ Layer (DOM)      │    │  Pipeline    │  │ Parser  │
│             │          │                  │    │              │  │         │
└─────────────┘          └──────────────────┘    └──────────────┘  └─────────┘
      │                             │                   │                │
      │                    ┌────────▼────────┐         │                │
      │                    │ Editor Adapter  │◄────────┘                │
      │                    │ (Monaco/CM/Ace) │                          │
      │                    └─────────────────┘                          │
      │                                                                  │
      └──────────────────────────────────────────────────────────────────┘
                              Chrome Process
                        (Windows 11 + Persistent
                         Profile + Hive Extension)
```

### Data Flow Workflow

```
1. LOGIN PHASE
   ┌─────────────────────────┐
   │ Start Browser + Context │ (persistent profile)
   └────────────┬────────────┘
                │
   ┌────────────▼────────────┐
   │ Verify Hive Extension   │ (must be installed/enabled)
   │ & Disable Other Ext.    │
   └────────────┬────────────┘
                │
   ┌────────────▼────────────┐
   │ Login with Credentials  │ (stored in secure config)
   │ via Hive Login Form     │
   └────────────┬────────────┘
                │
   ┌────────────▼────────────┐
   │ Persist Auth Session    │ (profile context saves cookies)
   └────────────┬────────────┘
                │
                ▼
   2. PROBLEM DISCOVERY PHASE
   ┌─────────────────────────┐
   │ Navigate to Problems    │
   │ List / Dashboard        │
   └────────────┬────────────┘
                │
   ┌────────────▼────────────┐
   │ Query DOM for Unsolved  │
   │ Problems (XPath/CSS)    │
   └────────────┬────────────┘
                │
   ┌────────────▼────────────┐
   │ Extract Problem Metadata│
   │ (title, ID, tags, etc) │
   └────────────┬────────────┘
                │
   ┌────────────▼────────────┐
   │ Store in StateManager   │
   │ (for recovery)          │
   └────────────┬────────────┘
                │
                ▼
   3. PROBLEM SOLVING PHASE (per problem, up to 5 attempts)
   ┌─────────────────────────┐
   │ Click on Problem        │
   │ Navigate to Editor      │
   └────────────┬────────────┘
                │
   ┌────────────▼────────────┐
   │ Detect Editor Type      │
   │ (Monaco/CodeMirror/Ace) │
   │ Load EditorAdapter      │
   └────────────┬────────────┘
                │
   ┌────────────▼────────────┐
   │ Read Problem Statement  │
   │ & Constraints from DOM  │
   └────────────┬────────────┘
                │
   ┌────────────▼────────────┐
   │ Query AI Solver Pipeline│
   │ (send problem details)  │
   └────────────┬────────────┘
                │
   ┌────────────▼────────────┐
   │ AI generates code       │
   │ (with provider routing) │
   └────────────┬────────────┘
                │
   ┌────────────▼────────────┐
   │ EditorAdapter injects   │
   │ code into editor        │
   │ (programmatic update)   │
   └────────────┬────────────┘
                │
   ┌────────────▼────────────┐
   │ Verify code in editor   │
   │ (parse + validate)      │
   └────────────┬────────────┘
                │
   ┌────────────▼────────────┐
   │ Click Submit Button     │
   │ Wait for Verdict        │
   └────────────┬────────────┘
                │
   ┌────────────▼────────────┐
   │ Parse Verdict           │
   │ (Accepted/WA/RE/TLE)    │
   └────────────┬────────────┘
                │
                ├─ Accepted? ──► Go to Step 4
                │
                └─ Failed? ──┬─► Attempt < 5? ──► Extract error ──┐
                             │                                     │
                             └─ Attempt ≥ 5? ──► Mark FAILED ─────┘
                                                  │
                                    ┌─────────────┘
                                    │
                                    ▼
                    Query AI Solver (debug mode):
                    "Here's the error: [error message]
                     Previous code: [code]
                     Generate fixed code"
                                    │
                                    └──► Loop back to code injection
                |
                ▼
   4. NEXT PROBLEM
   ┌─────────────────────────┐
   │ Navigate Back to List   │
   │ Mark Problem as Done    │
   └────────────┬────────────┘
                │
   ┌────────────▼────────────┐
   │ Continue Loop or Exit   │
   │ (batch mode / manual)   │
   └─────────────────────────┘
```

### Integration Points

| Integration | Purpose | Protocol |
|---|---|---|
| **Playwright ↔ Chrome** | Browser automation, DOM inspection, click/type actions | Playwright Browser Automation Protocol |
| **Chrome ↔ Hive Extension** | Hive security mechanism; bot must not bypass | Native Chrome Extension |
| **Bot ↔ Editor DOM** | Code injection into Monaco/CodeMirror/Ace editor | JavaScript Injection + API calls |
| **Bot ↔ AI Provider** | Code generation, debugging, re-solving | REST API (OpenAI, Gemini, Groq, etc.) |
| **StateManager ↔ Disk** | Crash recovery, progress tracking | JSON file + atomic writes |
| **Browser ↔ Persistent Profile** | Authentication persistence | Chrome user data directory |

---

## Components and Interfaces

### Module Structure

```
hive-bot/
├── src/
│   ├── browser/                 # Playwright browser management
│   │   ├── __init__.py
│   │   ├── manager.py           # BrowserManager class
│   │   └── context.py           # Browser context configuration
│   │
│   ├── auth/                    # Authentication & session management
│   │   ├── __init__.py
│   │   ├── credentials.py       # Credential loading & validation
│   │   ├── login.py             # Hive login workflow
│   │   └── session.py           # Session verification
│   │
│   ├── hive/                    # Hive platform interaction
│   │   ├── __init__.py
│   │   ├── dom_queries.py       # DOM inspection utilities
│   │   ├── problem_list.py      # Problem discovery & extraction
│   │   ├── problem_navigator.py # Problem detail navigation
│   │   ├── verdict_parser.py    # Result parsing (AC/WA/RE/TLE)
│   │   └── ui_constants.py      # XPath & CSS selectors
│   │                            # IMPORTANT: Selectors discovered via DevTools inspection,
│   │                            # NOT invented before live inspection (see Phase 1 Task #1)
│   │
│   ├── editor/                  # Code editor integration
│   │   ├── __init__.py
│   │   ├── adapter.py           # EditorAdapter interface
│   │   ├── monaco.py            # Monaco editor provider
│   │   ├── codemirror.py        # CodeMirror editor provider
│   │   ├── ace.py               # Ace editor provider
│   │   └── detector.py          # Editor type detection
│   │
│   ├── solver/                  # AI code solving pipeline
│   │   ├── __init__.py
│   │   ├── interface.py         # Solver interface & types
│   │   ├── ai_solver.py         # Main solver orchestrator
│   │   ├── providers/           # AI provider implementations
│   │   │   ├── __init__.py
│   │   │   ├── base.py          # BaseProvider abstract class
│   │   │   ├── openai_provider.py
│   │   │   ├── gemini_provider.py
│   │   │   └── ollama_provider.py (stub for future local models)
│   │   ├── prompts.py           # Problem-to-prompt generation
│   │   └── retry_logic.py       # Retry & debugging loop
│   │
│   ├── state/                   # State management & persistence
│   │   ├── __init__.py
│   │   ├── manager.py           # StateManager class
│   │   ├── models.py            # Problem, Submission, Progress models
│   │   ├── persistence.py       # File I/O & atomic writes
│   │   └── machine.py           # State machine coordinator
│   │
│   ├── utils/                   # Shared utilities
│   │   ├── __init__.py
│   │   ├── logging_config.py    # Centralized logging setup
│   │   ├── config.py            # Configuration loader
│   │   ├── constants.py         # Global constants
│   │   ├── errors.py            # Custom exception classes
│   │   └── helpers.py           # Common utility functions
│   │
│   ├── main.py                  # Entry point & CLI
│   └── bot.py                   # Main Bot orchestrator class
│
├── tests/                       # Unit & integration tests
├── config/
│   ├── default_config.yaml      # Default configuration
│   └── secrets.example.yaml     # Template for secrets
├── logs/                        # Runtime logs (git-ignored)
├── state/                       # State persistence (git-ignored)
├── requirements.txt
└── README.md
```

### Component Responsibilities

#### BrowserManager (browser/manager.py)

```
class BrowserManager:
  - browser: playwright.Browser
  - context: playwright.BrowserContext
  - page: playwright.Page
  
  + __init__(profile_path: str, headless: bool)
  + launch_browser() -> None
  + create_context() -> None
  + verify_hive_extension() -> bool
  + disable_other_extensions() -> None
  + get_page() -> playwright.Page
  + close() -> None
  + is_connected() -> bool
```

**Responsibilities**:
- Launch Chrome with persistent profile
- Manage browser lifecycle (launch, close, reconnect on crash)
- Ensure Hive Extension is enabled
- Disable non-essential extensions (security & performance)
- Provide page object for DOM queries and interactions
- Handle browser crashes with recovery logic

---

#### AuthManager (auth/login.py)

```
class AuthManager:
  - browser_manager: BrowserManager
  - credentials: Credentials
  - session_config: dict
  
  + login(email: str, password: str) -> bool
  + verify_session() -> bool
  + logout() -> None
  + is_authenticated() -> bool
  + wait_for_dashboard() -> None
```

**Responsibilities**:
- Perform Hive login using Playwright
- Wait for successful authentication signals
- Verify session state (cookies, tokens)
- Handle login failures and retry logic
- Ensure persistent session for next runs

---

#### ProblemDiscovery (hive/problem_list.py)

```
class ProblemDiscovery:
  - page: playwright.Page
  
  + fetch_problems() -> List[Problem]
  + get_unsolved_count() -> int
  + extract_problem_metadata(element) -> Problem
  + navigate_to_problem(problem_id: str) -> bool
  + parse_problem_details() -> ProblemDetails
```

**Responsibilities**:
- Query Hive problem list DOM via actual selectors (discovered at runtime)
- Extract unsolved problem cards
- Parse metadata (title, ID, difficulty, tags)
- Navigate to individual problem pages
- Extract problem constraints and examples

**CRITICAL - DOM INSPECTION FIRST**:
- **No selectors are invented or assumed.** Before Phase 1 implementation:
  1. Open real Hive problem page in browser
  2. Inspect DOM structure (F12 DevTools)
  3. Identify actual problem list selectors (XPath/CSS)
  4. Document discovered selectors in `ui_constants.py`
  5. Do NOT hard-code assumptions into code
- Problem status mapping (discovered at runtime):
  - "Try Again" → SOLVED status (skip problem)
  - "Continue" → UNSOLVED status (process problem)
  - "Solve" → UNSOLVED status (process problem)
  - **Note**: This mapping must be verified against actual Hive UI in Phase 1

---

#### EditorAdapter (editor/adapter.py)

```
interface EditorAdapter:
  + get_current_code() -> str
  + set_code(code: str) -> bool
  + clear_code() -> bool
  + get_editor_state() -> dict
  + verify_code_inserted(expected: str) -> bool
  + focus_editor() -> None
  + wait_for_ready() -> None
```

**Implementations**:
- `MonacoAdapter`: Monaco Editor (VS Code) API
- `CodeMirrorAdapter`: CodeMirror (lightweight) API
- `AceAdapter`: Ace Editor (Cloud9) API
- `GenericAdapter`: Fallback (text insertion + JavaScript)

---

#### AISolver (solver/ai_solver.py)

```
class AISolver:
  - providers: List[BaseProvider]
  - current_provider_index: int
  - retry_count: int
  
  + solve(problem: Problem, language: str) -> str
  + solve_with_context(
      problem: Problem,
      language: str,
      error: str,
      previous_code: str
    ) -> str
  + select_provider() -> BaseProvider
  + fallback_to_next_provider() -> bool
```

**Responsibilities**:
- Route solve requests to configured AI providers
- Manage provider fallback chain (if primary fails)
- Generate prompts from problem details
- Invoke provider APIs with retry logic
- Return generated code string

---

#### StateManager (state/manager.py)

```
class StateManager:
  - state_file: Path
  - current_state: BotState
  - lock: threading.Lock
  
  + load_state() -> BotState
  + save_state(state: BotState) -> None
  + get_current_problem() -> Optional[Problem]
  + mark_problem_solved(problem_id: str) -> None
  + mark_problem_failed(problem_id: str, reason: str) -> None
  + record_submission(
      problem_id: str,
      attempt: int,
      verdict: Verdict,
      code: str
    ) -> None
  + get_progress() -> Progress
  + rollback_to_last_checkpoint() -> None
```

**Responsibilities**:
- Load/save bot state to persistent storage
- Track completed, failed, and in-progress problems
- Record submission attempts and verdicts
- Enable crash recovery (resume from last checkpoint)
- Manage concurrent access with locks

---

#### StateMachine (state/machine.py)

```
enum BotState:
  IDLE, LOGGING_IN, ON_PROBLEM_LIST, 
  LOADING_PROBLEM, SOLVING, SUBMITTING,
  VERDICT_PARSING, RETRY_WAITING, COMPLETE, ERROR

class StateMachine:
  - current_state: BotState
  - state_manager: StateManager
  - event_handlers: Dict[BotState, Callable]
  
  + transition(new_state: BotState) -> None
  + handle_state(state: BotState) -> bool
  + on_error(error: Exception) -> BotState
  + reset() -> None
```

**Responsibilities**:
- Define valid state transitions
- Enforce workflow order
- Handle state-specific logic
- Integrate with StateManager for persistence
- Provide error state transitions

---

## Data Models

### Problem (state/models.py)

```python
@dataclass
class Problem:
    problem_id: str
    title: str
    difficulty: str          # "Easy", "Medium", "Hard"
    category: str            # "Array", "String", "Tree", etc.
    tags: List[str]
    time_limit: int          # seconds
    memory_limit: int        # MB
    statement: str           # Problem description
    examples: List[Tuple[str, str]]  # [(input, output), ...]
    languages_supported: List[str]   # ["Python", "Java", "C++", "C"]
    solved: bool = False
    failed: bool = False
    attempts: int = 0
    last_error: Optional[str] = None
```

### Submission (state/models.py)

```python
@dataclass
class Submission:
    problem_id: str
    attempt_number: int
    code: str
    language: str
    verdict: Verdict           # enum: ACCEPTED, WRONG_ANSWER, RUNTIME_ERROR, TIME_LIMIT, etc.
    error_message: Optional[str]
    execution_time: Optional[float]  # seconds
    memory_used: Optional[int]       # MB
    timestamp: datetime
```

### BotState (state/models.py)

```python
@dataclass
class BotState:
    current_problem: Optional[Problem] = None
    problems_queue: List[Problem] = field(default_factory=list)
    completed_problems: List[str] = field(default_factory=list)
    failed_problems: List[str] = field(default_factory=list)
    submissions: List[Submission] = field(default_factory=list)
    current_attempt: int = 0
    workflow_state: WorkflowState = WorkflowState.IDLE
    last_checkpoint: datetime = field(default_factory=datetime.now)
    session_id: str = field(default_factory=lambda: str(uuid.uuid4()))
```

---

## Editor Integration

### Runtime Editor Detection

**CRITICAL**: The editor type is NOT known in advance. Detection happens at runtime when the bot reaches each problem page.

```python
class EditorDetector:
    """Detect actual editor type at runtime"""
    
    async def detect_editor_type(page: Page) -> EditorType:
        """
        Detect editor in this order:
        1. Window globals (most reliable)
        2. DOM inspection (container/class attributes)
        3. Fallback to generic adapter
        
        Returns: EditorType enum or EditorType.GENERIC
        """
        
        # Step 1: Check window globals
        # Fastest and most reliable method
        editor_check = await page.evaluate("""
            () => {
                if (typeof window.monaco !== 'undefined') return 'monaco';
                if (typeof window.CodeMirror !== 'undefined') return 'codemirror';
                if (typeof window.ace !== 'undefined') return 'ace';
                if (typeof window.tinymce !== 'undefined') return 'tinymce';
                return null;
            }
        """)
        
        if editor_check:
            return EditorType(editor_check.upper())
        
        # Step 2: DOM inspection (classes, attributes)
        # Fallback when globals not available
        try:
            # Check for known editor containers
            monaco_found = await page.query_selector('.monaco-editor')
            if monaco_found:
                return EditorType.MONACO
            
            codemirror_found = await page.query_selector('.CodeMirror')
            if codemirror_found:
                return EditorType.CODEMIRROR
            
            ace_found = await page.query_selector('.ace_editor')
            if ace_found:
                return EditorType.ACE
            
            tinymce_found = await page.query_selector('.tinymce')
            if tinymce_found:
                return EditorType.TINYMCE
        except:
            pass  # DOM inspection failed, continue to fallback
        
        # Step 3: Fallback to generic adapter
        # Always available: textarea or contenteditable div
        return EditorType.GENERIC
    
    async def get_editor_adapter(
        page: Page,
        editor_type: EditorType
    ) -> EditorAdapter:
        """
        Get appropriate adapter for detected editor type.
        
        This enables robust fallback chain:
        If Monaco fails → try CodeMirror → try Ace → try generic
        """
        
        adapters = {
            EditorType.MONACO: MonacoAdapter(page),
            EditorType.CODEMIRROR: CodeMirrorAdapter(page),
            EditorType.ACE: AceAdapter(page),
            EditorType.TINYMCE: TinyMCEAdapter(page),
            EditorType.GENERIC: GenericAdapter(page),
        }
        
        return adapters.get(editor_type, GenericAdapter(page))
```

**Detection Workflow**:
1. Load problem page in browser
2. Call `EditorDetector.detect_editor_type(page)`
3. Get appropriate adapter via `EditorDetector.get_editor_adapter(page, detected_type)`
4. Use adapter for code injection
5. If injection fails → try fallback adapter (if available)

**Key Points**:
- **Runtime Discovery**: Always detect; never assume editor type
- **Robust Fallback**: Monaco → CodeMirror → Ace → Generic
- **No Hard-Coding**: Supports future Hive UI changes
- **Graceful Degradation**: Generic adapter always available

### Editor Implementations

#### Detection Order

```python
class EditorDetector:
    async def detect_editor_type() -> EditorType:
        """
        Query page.evaluate() to detect:
        1. window.monaco (Monaco)
        2. window.CodeMirror (CodeMirror)
        3. window.ace (Ace)
        4. Fallback to generic approach
        
        NOTE: This is called at runtime on every problem page.
        Do not hard-code editor type; always detect.
        """
```

**Robust Fallback Chain**:
If Monaco detection fails → try CodeMirror → try Ace → try generic
This ensures bot doesn't fail if one detection method doesn't work.

#### Monaco Editor Integration

```python
class MonacoAdapter(EditorAdapter):
    async def set_code(code: str) -> bool:
        """
        Use Monaco Editor API:
        1. Get editor instance: window.monaco.editor.getModels()[0]
        2. Set value: editor.setValue(code)
        3. Format: editor.getAction('editor.action.formatDocument').run()
        4. Verify: editor.getValue() == code
        """
```

#### CodeMirror Integration

```python
class CodeMirrorAdapter(EditorAdapter):
    async def set_code(code: str) -> bool:
        """
        Use CodeMirror API:
        1. Get editor instance: window.CodeMirror.editors[0] or similar
        2. Set value: editor.setValue(code)
        3. Clear history: editor.clearHistory()
        4. Verify: editor.getValue() == code
        """
```

#### Ace Editor Integration

```python
class AceAdapter(EditorAdapter):
    async def set_code(code: str) -> bool:
        """
        Use Ace API:
        1. Get session: editor.getSession()
        2. Set value: session.setValue(code)
        3. Set language: session.setMode('ace/mode/...')
        4. Verify: session.getValue() == code
        """
```

#### Generic Fallback

```python
class GenericAdapter(EditorAdapter):
    async def set_code(code: str) -> bool:
        """
        Fallback approach:
        1. Locate textarea or contenteditable div via XPath
        2. Focus element
        3. Select all: Ctrl+A
        4. Delete
        5. Type code (or paste via clipboard)
        6. Verify by re-reading
        """
```

**Why Programmatic vs. Copy-Paste**:
- Editors maintain internal state (AST, formatting, undo history)
- Simple copy-paste bypasses this and can cause parse errors
- Programmatic insertion ensures editor internals are updated
- Better for editor-specific features (syntax highlighting, validation)

---

## AI Solver Architecture

```python
class BaseProvider(ABC):
    """Abstract base for all AI providers"""
    
    @abstractmethod
    async def generate_code(
        self,
        problem: Problem,
        language: str,
        context: Optional[Dict] = None
    ) -> str:
        """Generate solution code"""
    
    @abstractmethod
    async def debug_code(
        self,
        problem: Problem,
        language: str,
        error: str,
        previous_code: str
    ) -> str:
        """Generate fixed code based on error"""
    
    @abstractmethod
    async def is_available() -> bool:
        """Check if provider is configured and responding"""
    
    async def health_check() -> bool:
        """Verify API connectivity"""
```

### Provider Interface

```python
class BaseProvider(ABC):
    """Abstract base for all AI providers"""
    
    @abstractmethod
    async def generate_code(
        self,
        problem: Problem,
        language: str,
        context: Optional[Dict] = None
    ) -> str:
        """Generate solution code"""
    
    @abstractmethod
    async def debug_code(
        self,
        problem: Problem,
        language: str,
        error: str,
        previous_code: str
    ) -> str:
        """Generate fixed code based on error"""
    
    @abstractmethod
    async def is_available() -> bool:
        """Check if provider is configured and responding"""
    
    async def health_check() -> bool:
        """Verify API connectivity"""
```

### OpenAI Provider

```python
class OpenAIProvider(BaseProvider):
    """Uses OpenAI GPT-4 / GPT-3.5 for code generation"""
    
    def __init__(self, api_key: str, model: str = "gpt-4"):
        self.client = OpenAI(api_key=api_key)
        self.model = model
    
    async def generate_code(problem, language, context=None) -> str:
        """
        Construct prompt from problem + language.
        Query OpenAI API.
        Parse code from response.
        """
```

### Gemini Provider

```python
class GeminiProvider(BaseProvider):
    """Uses Google Gemini for code generation"""
    
    def __init__(self, api_key: str):
        self.client = genai.Client(api_key=api_key)
```

### Groq Provider

```python
class GroqProvider(BaseProvider):
    """
    Uses Groq API for ultra-fast code generation.
    
    Groq is OpenAI-compatible with ultra-low latency (800+ tokens/sec).
    Default models: "mixtral-8x7b-32768" (fast) or "llama2-70b-4096" (powerful).
    Perfect for real-time competitive coding with retry loops.
    """
    
    def __init__(self, api_key: str, model: str = "mixtral-8x7b-32768"):
        from groq import Groq
        self.client = Groq(api_key=api_key)
        self.model = model
    
    async def generate_code(problem, language, context=None) -> str:
        """
        Use Groq API for ultra-fast code generation.
        Leverages 32k context window for large problem statements.
        """
    
    async def debug_code(
        self,
        problem: Problem,
        language: str,
        error: str,
        previous_code: str
    ) -> str:
        """Fast debugging with context of previous attempt"""
```

**Groq Advantages**:
- **Ultra-Low Latency**: 800+ tokens/sec vs 20-30 for OpenAI
- **Cost-Effective**: $0.50-$1.50 per 1M tokens vs $10-30 for OpenAI
- **OpenAI-Compatible**: Drop-in replacement API
- **Large Context**: 32k context window for detailed problem statements
- **Real-Time Suitable**: Perfect for competitive coding with retries

### Ollama Provider (Stub for Future)

```python
class OllamaProvider(BaseProvider):
    """Future: local Ollama models (llama2, mistral, etc)"""
    
    def __init__(self, base_url: str = "http://localhost:11434", model: str = "llama2"):
        self.base_url = base_url
        self.model = model
```

### Provider Routing & Fallback

```python
class AISolver:
    def __init__(self, providers: List[BaseProvider]):
        self.providers = providers
        self.current_index = 0
    
    async def solve(problem: Problem, language: str) -> str:
        """
        Try providers in order (recommended fallback chain):
        1. Groq (ultra-fast, cost-effective, 800+ tokens/sec)
        2. OpenAI (reliable, powerful, good for complex problems)
        3. Gemini (good alternative if Groq/OpenAI unavailable)
        4. Ollama (local, no cost, good for offline or privacy)
        
        On failure, fallback to next provider.
        If all fail, raise SolverError.
        
        Provider selection strategy:
        - Groq is default primary (fastest, cheapest, real-time suitable)
        - OpenAI as secondary (proven reliability, handles edge cases)
        - Gemini as tertiary (Google quality, parallel option)
        - Ollama as fallback (local/offline capability)
        """
```

**Recommended Provider Chain**:
```yaml
primary_provider: "groq"
fallback_chain: ["openai", "gemini", "ollama"]
```

**Rationale**:
- **Speed**: Groq's ultra-low latency (800+ tokens/sec) ideal for retries
- **Cost**: Groq significantly cheaper than OpenAI
- **Reliability**: OpenAI fallback ensures solutions if Groq unavailable
- **Diversity**: Gemini & Ollama provide additional fallback paths
- **Competitive Coding**: Fixed, predictable solutions benefit from fast inference

### Prompt Engineering

```python
def construct_problem_prompt(
    problem: Problem,
    language: str,
    include_examples: bool = True
) -> str:
    """
    Build prompt from problem metadata:
    
    "Solve the following problem in [language]:
    
    Title: [problem.title]
    Difficulty: [problem.difficulty]
    
    Problem Statement:
    [problem.statement]
    
    Constraints:
    - Time Limit: [problem.time_limit]s
    - Memory Limit: [problem.memory_limit]MB
    
    Examples:
    [examples formatted as test cases]
    
    Return ONLY the code, no explanation.
    Use standard I/O (input() / scanf, print / printf).
    "
    """
```

### Retry & Debugging Loop

```python
async def solve_with_retry(
    problem: Problem,
    language: str,
    max_attempts: int = 5
) -> Tuple[str, int]:
    """
    Attempt solving with retry loop:
    
    for attempt in range(1, max_attempts + 1):
        code = ai_solver.solve(problem, language)
        verdict, error = submit_and_parse(code)
        
        if verdict == ACCEPTED:
            return code, attempt
        
        if attempt < max_attempts:
            code = ai_solver.debug_code(
                problem=problem,
                language=language,
                error=error,
                previous_code=code
            )
            # Loop again
    
    raise SolverError(f"Failed after {max_attempts} attempts")
    """
```

---

## State Management

### Workflow States

```python
class WorkflowState(Enum):
    IDLE                 = "idle"              # Initial state
    LOGGING_IN           = "logging_in"        # Auth in progress
    AUTHENTICATED        = "authenticated"     # Login successful
    DISCOVERING_PROBLEMS = "discovering"      # Fetching problem list
    PROBLEM_LIST_READY   = "problem_list"     # Problems loaded
    PROBLEM_LOADING      = "problem_loading"  # Loading problem details
    PROBLEM_READY        = "problem_ready"    # Problem ready to solve
    GENERATING_SOLUTION  = "generating"      # AI solver running
    SOLUTION_READY       = "solution_ready"   # Code generated
    INJECTING_CODE       = "injecting"        # Code into editor
    CODE_VERIFIED        = "code_verified"    # Code confirmed in editor
    SUBMITTING           = "submitting"       # Submit button clicked
    VERDICT_PARSING      = "verdict_parsing"  # Waiting for result
    VERDICT_RECEIVED     = "verdict_received" # Result parsed
    RETRY_WAITING        = "retry_waiting"    # Before retry
    PROBLEM_SOLVED       = "problem_solved"   # Accepted verdict
    PROBLEM_FAILED       = "problem_failed"   # Max attempts exceeded
    CONTINUING           = "continuing"       # Next problem
    SHUTDOWN             = "shutdown"         # Graceful shutdown
    ERROR_RECOVERY       = "error_recovery"   # Crash recovery
    ERROR                = "error"            # Fatal error
```

### State Transition Diagram

```
        IDLE
         │
         ▼
    LOGGING_IN ──────────────► ERROR
         │
         ▼
    AUTHENTICATED
         │
         ▼
    DISCOVERING_PROBLEMS
         │
         ▼
    PROBLEM_LIST_READY
         │
    ┌────┴────────────────────────────┐
    │                                 │
    ▼                                 ▼
PROBLEM_LOADED                    SHUTDOWN
    │
    ▼
GENERATING_SOLUTION ─────────► ERROR
    │
    ▼
SOLUTION_READY
    │
    ▼
INJECTING_CODE ────────────► ERROR
    │
    ▼
CODE_VERIFIED
    │
    ▼
SUBMITTING ────────────────► ERROR
    │
    ▼
VERDICT_PARSING
    │
    ▼
VERDICT_RECEIVED
    │
    ├─ ACCEPTED ──────► PROBLEM_SOLVED ──┐
    │                                    │
    ├─ FAILED ─────────► RETRY_WAITING ──┤
    │   (attempt < 5)        │           │
    │                        ▼           │
    │                  GENERATING_SOLUTION (retry)
    │                        │           │
    └───────────────────────◄┘           │
    │                                    │
    ├─ FAILED & attempt ≥ 5 ──► PROBLEM_FAILED
    │                              │
    └──────────────────────────────┘
         │
         ▼
    CONTINUING
         │
    ┌────┴────────────────┐
    │                     │
    More problems?   No more problems
    │                     │
    ▼                     ▼
PROBLEM_LOADING      SHUTDOWN
```

### State Transition Conditions

```python
class StateMachine:
    transitions = {
        WorkflowState.IDLE: {
            WorkflowState.LOGGING_IN: lambda: user_requested_start(),
        },
        WorkflowState.LOGGING_IN: {
            WorkflowState.AUTHENTICATED: lambda: login_successful(),
            WorkflowState.ERROR: lambda: login_failed(),
        },
        WorkflowState.AUTHENTICATED: {
            WorkflowState.DISCOVERING_PROBLEMS: lambda: True,
        },
        WorkflowState.DISCOVERING_PROBLEMS: {
            WorkflowState.PROBLEM_LIST_READY: lambda: problems_fetched(),
            WorkflowState.ERROR: lambda: fetch_failed(),
        },
        WorkflowState.PROBLEM_LIST_READY: {
            WorkflowState.PROBLEM_LOADING: lambda: has_unsolved_problems(),
            WorkflowState.SHUTDOWN: lambda: not has_unsolved_problems(),
        },
        WorkflowState.PROBLEM_LOADING: {
            WorkflowState.PROBLEM_READY: lambda: problem_loaded(),
            WorkflowState.ERROR: lambda: load_failed(),
        },
        WorkflowState.PROBLEM_READY: {
            WorkflowState.GENERATING_SOLUTION: lambda: True,
        },
        WorkflowState.GENERATING_SOLUTION: {
            WorkflowState.SOLUTION_READY: lambda: code_generated(),
            WorkflowState.ERROR: lambda: generation_failed(),
        },
        WorkflowState.SOLUTION_READY: {
            WorkflowState.INJECTING_CODE: lambda: True,
        },
        WorkflowState.INJECTING_CODE: {
            WorkflowState.CODE_VERIFIED: lambda: code_verified(),
            WorkflowState.ERROR: lambda: injection_failed(),
        },
        WorkflowState.CODE_VERIFIED: {
            WorkflowState.SUBMITTING: lambda: True,
        },
        WorkflowState.SUBMITTING: {
            WorkflowState.VERDICT_PARSING: lambda: submit_clicked(),
            WorkflowState.ERROR: lambda: submit_failed(),
        },
        WorkflowState.VERDICT_PARSING: {
            WorkflowState.VERDICT_RECEIVED: lambda: verdict_parsed(),
            WorkflowState.ERROR: lambda: parse_failed(),
        },
        WorkflowState.VERDICT_RECEIVED: {
            WorkflowState.PROBLEM_SOLVED: lambda: verdict == ACCEPTED,
            WorkflowState.RETRY_WAITING: lambda: verdict != ACCEPTED and current_attempt < 5,
            WorkflowState.PROBLEM_FAILED: lambda: verdict != ACCEPTED and current_attempt >= 5,
        },
        WorkflowState.RETRY_WAITING: {
            WorkflowState.GENERATING_SOLUTION: lambda: retry_delay_elapsed(),
        },
        WorkflowState.PROBLEM_SOLVED: {
            WorkflowState.CONTINUING: lambda: True,
        },
        WorkflowState.PROBLEM_FAILED: {
            WorkflowState.CONTINUING: lambda: True,
        },
        WorkflowState.CONTINUING: {
            WorkflowState.PROBLEM_LIST_READY: lambda: True,
        },
    }
```

---

## Configuration & Environment Management

### Configuration Schema (config/default_config.yaml)

```python
class HiveBotError(Exception):
    """Base exception"""
    pass

class AuthenticationError(HiveBotError):
    """Login failed"""
    pass

class DOMError(HiveBotError):
    """Selectors not found or DOM changed"""
    pass

class EditorError(HiveBotError):
    """Code injection or editor detection failed"""
    pass

class SolverError(HiveBotError):
    """All AI providers failed"""
    pass

class VerdictError(HiveBotError):
    """Could not parse verdict from submission"""
    pass

class StateError(HiveBotError):
    """Invalid state transition"""
    pass

class NetworkError(HiveBotError):
    """API or browser connection error"""
    pass

class TimeoutError(HiveBotError):
    """Operation exceeded timeout"""
    pass
```

### 6.2 Error Recovery Strategies

| Error Type | Recovery Strategy |
|---|---|
| **DOM Selector Not Found** | 1. Refresh page & retry (selector may be delayed) 2. Log DOM snapshot 3. Raise exception (needs manual UI inspection) |
| **Editor Not Detected** | 1. Try all adapter types sequentially 2. Use generic fallback (text insertion) |
| **AI Provider Timeout** | 1. Fallback to next provider in chain 2. Increase timeout (if configured) 3. Raise SolverError if all fail |
| **Browser Crash** | 1. Detect via page.isClosed() 2. Load StateManager checkpoint 3. Restart browser 4. Resume from last problem |
| **Authentication Expired** | 1. Detect: 403 on dashboard, redirected to login 2. Re-run login flow 3. Resume problem list discovery |
| **Network Timeout (Hive)** | 1. Wait & retry (exponential backoff) 2. If persistent: mark problem as "network_issue" 3. Continue to next problem |
| **Submission Parsing Failed** | 1. Screenshot DOM state 2. Log raw response 3. Retry submission after delay 4. Mark as "verdict_unknown" |
| **Code Injection Failed** | 1. Verify editor is ready 2. Try again with longer wait 3. Fall back to generic adapter 4. Raise EditorError if all fail |

### 6.3 Checkpoint & Recovery System

```python
class StateManager:
    def save_checkpoint(self):
        """
        Save atomic checkpoint after each major milestone:
        - Login successful
        - Problem list fetched
        - Problem loaded
        - Code generated
        - Code injected
        - Submission verdict received
        
        Structure:
        {
            "checkpoint_timestamp": "2024-01-15T10:23:45Z",
            "workflow_state": "verdict_received",
            "current_problem_id": "prob_123",
            "current_attempt": 2,
            "submissions": [...],
            "completed_problems": [...],
            "failed_problems": [...]
        }
        """
    
    def load_checkpoint(self) -> BotState:
        """
        Load last checkpoint on startup.
        Resume from exact state (problem, attempt count, etc).
        If checkpoint missing, start fresh.
        """
```

### 6.4 Logging & Observability

```python
# Comprehensive logging throughout workflow

logging.info("Logging in as user: {email}")
logging.debug(f"DOM snapshot: {page.content()[:500]}...")
logging.warning(f"Selector '{xpath}' not found, retrying...")
logging.error(f"AI provider failed: {error}", exc_info=True)
logging.info(f"Checkpoint saved: {checkpoint_file}")

# Screenshot on critical errors
page.screenshot(path=f"logs/error_{timestamp}.png")
```

---

### Environment Variables

```bash
# Required: Hive login credentials
export HIVE_USERNAME="your_username"
export HIVE_PASSWORD="your_password"
export HIVE_LOGIN_URL="https://hive.smartinterviews.in/contests/YOUR_CONTEST_NAME"

# Note: HIVE_LOGIN_URL is the complete login page URL provided by the user
# Bot does not construct this URL; it is used as-is for authentication

# At least one AI provider required (Groq recommended)
export GROQ_API_KEY="gsk_..."
export OPENAI_API_KEY="sk-..."
export GEMINI_API_KEY="AIza..."

# Optional
export OLLAMA_BASE_URL="http://localhost:11434"
export HIVE_BOT_LOG_LEVEL="DEBUG"
export HIVE_BOT_STATE_DIR="/tmp/hive_state"
```

### Configuration Loader

```python
class ConfigManager:
    """
    Load config from:
    1. default_config.yaml (bundled)
    2. ~/.hive_bot/config.yaml (user override)
    3. Environment variables (highest priority)
    
    Validate:
    - All required fields present
    - Valid URLs, timeouts, enums
    - At least one AI provider configured
    """
```

---

## IMPORTANT: Selector and DOM Inspection Strategy

**CRITICAL REQUIREMENT FOR PHASE 1 IMPLEMENTATION:**

Selectors are **NOT invented or assumed before live inspection.** The bot must discover real DOM selectors at runtime.

### Phase 1 Task #1: DOM Inspection Process

Before implementing problem discovery code:

1. **Open real Hive problem page** in browser
2. **Open DevTools** (Press F12)
3. **Inspect DOM structure**:
   - Right-click on problem card → "Inspect" or "Inspect Element"
   - Note the HTML structure, class names, IDs, attributes
4. **Identify actual selectors**:
   - Problem card selector: `//div[@class='...']` or equivalent
   - Status button/text selector: `//button[text()='Continue']` or similar
   - Problem title selector
   - Difficulty indicator selector
   - Tags/categories selector
5. **Document discovered selectors** in `ui_constants.py`
6. **Do NOT guess** – use only what you see in DevTools
7. **Then implement** problem discovery using discovered selectors

### Why This Matters

- Hive UI changes frequently; hard-coded assumptions break quickly
- Actual selectors may differ from documentation
- Real Hive UI inspection is authoritative
- Phase 1 task establishes accurate selector foundation for Phases 2-7
- Saves debugging time later when UI changes occur

### Design Document Shows Examples Only

All selector examples in this design (XPath, CSS, DOM queries) are **templates only**. 

**Actual selectors must be discovered** during Phase 1 implementation via DevTools inspection. Do not assume these examples will work without verification.

---

## Correctness Properties

The following formal properties must be satisfied by the system:

### Authentication Correctness
- **Property**: If `login()` returns `true`, the resulting session is valid for subsequent API calls
- **Enforcement**: Session verification before proceeding to problem discovery
- **Test**: `test_login_success()` verifies authenticated cookies persist

### Problem Discovery Completeness
- **Property**: All unsolved problems are discovered; no unsolved problem is missed
- **Enforcement**: Query entire problem list via pagination; filter by "solved" flag
- **Test**: `test_problem_fetch_completeness()` validates all problems returned

### Editor Integration Correctness
- **Property**: Code injected into editor matches generated code exactly (byte-for-byte, including whitespace)
- **Enforcement**: Programmatic API calls that update editor internals; verification step after injection
- **Test**: `test_code_injection_verification()` compares `expected_code == editor.getValue()`

### Submission Atomicity
- **Property**: Exactly one submission per problem per attempt (no duplicate submissions, no lost submissions)
- **Enforcement**: State machine transitions prevent re-submission; submission ID tracked in state
- **Test**: `test_submission_atomicity()` verifies state.submissions list has no duplicates

### State Machine Consistency
- **Property**: State machine never enters invalid states; all transitions are valid and documented
- **Enforcement**: Transition table defines all valid paths; invalid transitions raise `StateError`
- **Test**: `test_invalid_state_transitions()` attempts illegal transitions

### Retry Logic Bounds
- **Property**: Maximum 5 attempts per problem enforced; bot never retries > 5 times
- **Enforcement**: Attempt counter incremented per retry; state transitions to `PROBLEM_FAILED` if `attempt >= 5`
- **Test**: `test_retry_max_attempts()` verifies counter stops at 5

### Provider Fallback Correctness
- **Property**: If primary provider fails, secondary is attempted (and tertiary, etc.); if all fail, exception raised
- **Enforcement**: Try-catch around each provider; loop to next on failure; raise `SolverError` if all exhausted
- **Test**: `test_provider_fallback_chain()` mocks primary failure, verifies secondary called

### Checkpoint Persistence
- **Property**: State checkpoint saved after each major milestone; bot can resume from checkpoint without data loss
- **Enforcement**: `save_checkpoint()` called after: login, problem fetch, code injection, submission
- **Test**: `test_checkpoint_recovery()` saves, crashes, resumes, verifies state identical

### Session Recovery Correctness
- **Property**: If bot crashes mid-session, subsequent restart resumes from exact prior state (problem, attempt count, submissions)
- **Enforcement**: Load checkpoint on startup; verify state file exists and is valid JSON; resume workflow state
- **Test**: `test_crash_recovery()` simulates crash, verifies resume state

---

## Error Handling

### Error Categories

```python
class HiveBotError(Exception):
    """Base exception"""
    pass

class AuthenticationError(HiveBotError):
    """Login failed"""
    pass

class DOMError(HiveBotError):
    """Selectors not found or DOM changed"""
    pass

class EditorError(HiveBotError):
    """Code injection or editor detection failed"""
    pass

class SolverError(HiveBotError):
    """All AI providers failed"""
    pass

class VerdictError(HiveBotError):
    """Could not parse verdict from submission"""
    pass

class StateError(HiveBotError):
    """Invalid state transition"""
    pass

class NetworkError(HiveBotError):
    """API or browser connection error"""
    pass

class TimeoutError(HiveBotError):
    """Operation exceeded timeout"""
    pass
```

### Error Recovery Strategies

| Error Type | Recovery Strategy |
|---|---|
| **DOM Selector Not Found** | 1. Refresh page & retry (selector may be delayed) 2. Log DOM snapshot 3. Raise exception (needs manual UI inspection) |
| **Editor Not Detected** | 1. Try all adapter types sequentially 2. Use generic fallback (text insertion) |
| **AI Provider Timeout** | 1. Fallback to next provider in chain 2. Increase timeout (if configured) 3. Raise SolverError if all fail |
| **Browser Crash** | 1. Detect via page.isClosed() 2. Load StateManager checkpoint 3. Restart browser 4. Resume from last problem |
| **Authentication Expired** | 1. Detect: 403 on dashboard, redirected to login 2. Re-run login flow 3. Resume problem list discovery |
| **Network Timeout (Hive)** | 1. Wait & retry (exponential backoff) 2. If persistent: mark problem as "network_issue" 3. Continue to next problem |
| **Submission Parsing Failed** | 1. Screenshot DOM state 2. Log raw response 3. Retry submission after delay 4. Mark as "verdict_unknown" |
| **Code Injection Failed** | 1. Verify editor is ready 2. Try again with longer wait 3. Fall back to generic adapter 4. Raise EditorError if all fail |

### Checkpoint & Recovery System

```python
class StateManager:
    def save_checkpoint(self):
        """
        Save atomic checkpoint after each major milestone:
        - Login successful
        - Problem list fetched
        - Problem loaded
        - Code generated
        - Code injected
        - Submission verdict received
        
        Structure:
        {
            "checkpoint_timestamp": "2024-01-15T10:23:45Z",
            "workflow_state": "verdict_received",
            "current_problem_id": "prob_123",
            "current_attempt": 2,
            "submissions": [...],
            "completed_problems": [...],
            "failed_problems": [...]
        }
        """
    
    def load_checkpoint(self) -> BotState:
        """
        Load last checkpoint on startup.
        Resume from exact state (problem, attempt count, etc).
        If checkpoint missing, start fresh.
        """
```

### Logging & Observability

```python
# Comprehensive logging throughout workflow

logging.info("Logging in as user: {email}")
logging.debug(f"DOM snapshot: {page.content()[:500]}...")
logging.warning(f"Selector '{xpath}' not found, retrying...")
logging.error(f"AI provider failed: {error}", exc_info=True)
logging.info(f"Checkpoint saved: {checkpoint_file}")

# Screenshot on critical errors
page.screenshot(path=f"logs/error_{timestamp}.png")
```

---

## Testing Strategy

### Unit Testing Approach

**Component-Level Tests**:
- `test_browser_manager.py`: Browser launch, profile persistence, extension detection, crash recovery
- `test_auth.py`: Login success/failure, session persistence, timeout handling
- `test_problem_discovery.py`: Problem fetching, metadata extraction, unsolved filtering
- `test_editor_detector.py`: Editor type detection for Monaco, CodeMirror, Ace, generic fallback
- `test_state_manager.py`: Checkpoint save/load, concurrent access, persistence validation
- `test_ai_solver.py`: Provider selection, fallback chain, code generation mocking

### Integration Testing Approach

**Workflow-Level Tests**:
- `test_full_problem_workflow.py`: Login → Problem discovery → Editor detection → Code injection → Submission
- `test_retry_workflow.py`: Submission fails → AI re-solves → Code re-injected → Verdict accepted
- `test_crash_recovery.py`: Simulate crash mid-workflow → Load checkpoint → Resume exact state
- `test_provider_fallback.py`: Primary provider fails → Secondary provider called → Code generated successfully
- `test_state_machine.py`: Valid state transitions, invalid transitions raise exceptions

### Property-Based Testing Approach

**Property Test Library**: `pytest` with `hypothesis` or `fast-check` for randomized inputs

**Key Properties to Test**:
1. **Retry Bounds**: For any problem, `attempt_count <= 5` always holds
2. **Problem Discovery**: For any problem list query, `unsolved_problems ⊆ all_problems` always holds
3. **Code Verification**: For any injected code, `injected_code == editor.getValue()` always holds
4. **State Consistency**: For any workflow, `current_state ∈ valid_states` always holds
5. **Checkpoint Idempotence**: For any checkpoint save-load cycle, `loaded_state == saved_state` always holds

**Example Property Test**:
```python
@given(st.lists(st.text(), min_size=1))
def test_retry_count_never_exceeds_five(problems):
    """For any list of problems, retry count never exceeds 5"""
    for problem in problems:
        attempt = 0
        while problem.verdict != ACCEPTED and attempt < 5:
            submit_solution(problem)
            attempt += 1
        assert attempt <= 5  # Property holds
```

### Editor Adapter Testing

- `test_monaco_adapter.py`: Code injection via Monaco API, verification
- `test_codemirror_adapter.py`: Code injection via CodeMirror API, verification
- `test_ace_adapter.py`: Code injection via Ace API, verification
- `test_generic_adapter.py`: Fallback text insertion, verification

### Provider Fallback Testing

- `test_provider_chain.py`: Primary fails → secondary called → code generated
- `test_all_providers_fail.py`: All providers fail → `SolverError` raised
- `test_groq_primary.py`: Groq generates code successfully
- `test_openai_fallback.py`: Groq fails → OpenAI succeeds

### State Machine Transition Testing

- `test_valid_transitions.py`: All documented transitions execute successfully
- `test_invalid_transitions.py`: Attempted illegal transitions raise `StateError`
- `test_state_persistence.py`: Transitions persisted to checkpoint correctly

### Checkpoint & Recovery Testing

- `test_checkpoint_save.py`: Checkpoint file created with valid JSON
- `test_checkpoint_load.py`: Checkpoint loaded exactly as saved
- `test_checkpoint_recovery_workflow.py`: Bot resumes from checkpoint, completes remaining problems

### Test Coverage Goals

- **Target**: ≥ 85% code coverage
- **Critical Paths**: 100% coverage for auth, submission, state transitions
- **Error Paths**: 100% coverage for error handlers, fallbacks, retry logic

---

## 7. Configuration & Environment Management

### 7.1 Configuration Schema (config/default_config.yaml)

```yaml
# Browser & Platform
browser:
  headless: false                    # Show browser window
  browser_profile_path: "~/.hive_bot_profile"
  user_agent: "Mozilla/5.0..."       # Optional override
  timeout_default_ms: 30000

# Languages Supported
languages:
  default_supported: ["C", "C++", "Java", "Python"]
  # Note: Languages are configurable and discovered from problem page UI
  # LANGUAGE environment variable can override for specific problems
  # Bot must support dynamic language selection based on problem constraints
  auto_detect_from_ui: true          # Discover available languages at runtime

# Authentication
auth:
  credentials_source: "env"          # "env", "file", "secrets_manager"
  credentials_file: "~/.hive_creds"  # If source: file
  username_env: "HIVE_USERNAME"
  password_env: "HIVE_PASSWORD"
  login_timeout_s: 60

# Hive Platform
hive:
  # User provides complete login URL in HIVE_LOGIN_URL env variable
  # This is NOT derived from base_url
  login_url_env: "HIVE_LOGIN_URL"     # e.g., https://hive.smartinterviews.in/contests/smart-interviews-basic
  dashboard_url: "{login_url}/dashboard"  # Derived from login URL
  problem_list_xpath: "//div[contains(@class, 'problem-card')]"
  max_problems_per_session: 0        # 0 = unlimited

# AI Solver
solver:
  primary_provider: "groq"           # Recommended: groq (fast, cheap)
  fallback_chain: ["openai", "gemini", "ollama"]
  max_attempts_per_problem: 5
  generation_timeout_s: 60
  retry_delay_s: 2
  
  providers:
    groq:
      api_key_env: "GROQ_API_KEY"
      model: "mixtral-8x7b-32768"    # Fast, 32k context. Alt: "llama2-70b-4096"
      # Note: Model names are configurable. Current examples as of Sept 2026
      # Users should specify models available in their API subscriptions
      enabled: true
    openai:
      api_key_env: "OPENAI_API_KEY"
      model: "gpt-4o"                # Current as of Sept 2026. Alternatives: "gpt-4o-mini"
      # Note: Check OpenAI docs for latest available models
      temperature: 0.7
    gemini:
      api_key_env: "GEMINI_API_KEY"
      model: "gemini-2.0"            # Current as of Sept 2026. Alternatives: "gemini-1.5"
      # Note: Check Google docs for latest available models
    ollama:
      base_url: "http://localhost:11434"
      model: "llama2"
      enabled: false                 # STUB ONLY for Phase 1-6
      # Note: Ollama support deferred to Phase 7+ (local model integration)
      # API-only providers in initial phases: Groq, OpenAI, Gemini

# State Management
state:
  persistence_file: "~/.hive_bot/state.json"
  auto_checkpoint: true
  checkpoint_interval_problems: 1    # Save after each problem

# Logging
logging:
  level: "INFO"                      # DEBUG, INFO, WARNING, ERROR
  log_file: "logs/hive_bot.log"
  max_log_size_mb: 100
  backup_log_count: 5

# Feature Flags
features:
  dry_run: false                     # If true, skip actual submissions
  debug_mode: false                  # Extra logging
  screenshot_on_error: true
```

### 7.2 Environment Variables

```bash
# Required
export HIVE_EMAIL="user@example.com"
export HIVE_PASSWORD="secure_password"

# At least one AI provider required (Groq recommended)
export GROQ_API_KEY="gsk_..."
export OPENAI_API_KEY="sk-..."
export GEMINI_API_KEY="AIza..."

# Optional
export OLLAMA_BASE_URL="http://localhost:11434"
export HIVE_BOT_LOG_LEVEL="DEBUG"
export HIVE_BOT_STATE_DIR="/tmp/hive_state"
```

### 7.3 Configuration Loader

```python
class ConfigManager:
    """
    Load config from:
    1. default_config.yaml (bundled)
    2. ~/.hive_bot/config.yaml (user override)
    3. Environment variables (highest priority)
    
    Validate:
    - All required fields present
    - Valid URLs, timeouts, enums
    - At least one AI provider configured
    """
```

---

## Phase 1: Browser, Auth & Problem Discovery

This is the foundational phase. Phases 2-7 build on this.

### Phase 1 Scope

**Deliverables**:
1. Browser launch with persistent profile
2. Hive Extension verification
3. User login workflow (using HIVE_LOGIN_URL from environment)
4. Problem list discovery & parsing via actual DOM inspection
5. Basic state management (checkpoint saves)
6. Comprehensive logging

**CRITICAL Phase 1 Task #1: DOM Inspection & Selector Discovery**:
- Open real Hive problem page in browser
- Use DevTools (F12) to inspect DOM structure
- Identify actual selectors for:
  - Problem list container
  - Problem cards / list items
  - Problem status indicators ("Try Again", "Continue", "Solve" buttons/text)
  - Problem title, difficulty, tags
- Document ALL discovered selectors in `ui_constants.py`
- **Do NOT hard-code assumptions** into problem discovery code
- **Do NOT invent selectors** - only use discovered selectors
- Phase 1 implementation depends on this inspection

**Phase 1 Problem Status Mapping** (verified against real UI):
- **"Try Again"** → Problem marked as SOLVED (skip in unsolved list)
- **"Continue"** → Problem marked as UNSOLVED (include in problem discovery)
- **"Solve"** → Problem marked as UNSOLVED (include in problem discovery)
- **Verification**: Check real Hive UI to confirm this mapping during Phase 1 implementation

**Out of Scope** (Phases 2+):
- Problem details page navigation (Phase 2)
- Editor integration (Phase 3)
- Submission & verdict parsing (Phase 4)
- AI solver (Phase 5)
- Retry loop (Phase 6)
- Batch processing (Phase 7)

### Phase 1 Entry Point

```python
# main.py - Phase 1 execution

import asyncio
from src.bot import HiveBot

async def main():
    bot = HiveBot(config_path="config/default_config.yaml")
    
    try:
        # Phase 1: Setup & Auth
        await bot.initialize_browser()
        await bot.verify_hive_extension()
        await bot.login()
        
        # Phase 1: Problem Discovery
        problems = await bot.discover_problems()
        
        print(f"Found {len(problems)} unsolved problems:")
        for p in problems:
            print(f"  - {p.problem_id}: {p.title} ({p.difficulty})")
        
        # Save state checkpoint
        await bot.state_manager.save_checkpoint()
        
    except Exception as e:
        logging.error(f"Phase 1 failed: {e}", exc_info=True)
        raise
    finally:
        await bot.browser_manager.close()

if __name__ == "__main__":
    asyncio.run(main())
```

### Phase 1 Tests

```
tests/
├── test_browser_manager.py
│   ├── test_launch_browser()
│   ├── test_persistent_profile()
│   ├── test_hive_extension_detected()
│   └── test_browser_reconnection()
├── test_auth.py
│   ├── test_login_success()
│   ├── test_login_invalid_credentials()
│   ├── test_session_persistence()
│   └── test_login_timeout()
├── test_problem_discovery.py
│   ├── test_fetch_problems()
│   ├── test_problem_metadata_extraction()
│   ├── test_unsolved_filter()
│   └── test_dom_parsing()
├── test_editor_detector.py
│   ├── test_detect_monaco()
│   ├── test_detect_codemirror()
│   ├── test_detect_ace()
│   └── test_fallback_detection()
└── test_state_manager.py
    ├── test_save_checkpoint()
    ├── test_load_checkpoint()
    ├── test_concurrent_access()
    └── test_persistence()
```

---

## DRY_RUN Mode Implementation

### DRY_RUN Overview

When `config.features.dry_run = true`:
- All logic executes **up to the submission point**, then **STOPS**
- **No fabricated verdicts** - the bot does NOT pretend submissions passed
- **No pretending Hive approved non-submitted code**
- Code verified injected into editor, **halt before submit button**
- Useful for testing DOM inspection, editor detection, code generation **without affecting account**

### DRY_RUN Implementation

```python
class VerdictParser:
    async def parse_verdict(self) -> Verdict:
        if config.features.dry_run:
            # DRY RUN: Stop here, do NOT submit
            logging.info(f"[DRY_RUN] Code ready for submission (halting before submit)")
            logging.info(f"[DRY_RUN] Code verified in editor. Submission skipped.")
            # Return a placeholder that indicates dry-run completion
            return Verdict.DRY_RUN_COMPLETED  # Special enum value
        
        # Normal verdict parsing
        return self._parse_actual_verdict()
```

### CLI Flag

```bash
python -m src.main --dry-run --config config/default_config.yaml
```

---

## Logging & Error Recovery Patterns

### Structured Logging

```python
# Use structured logging for machine readability
import logging

logger = logging.getLogger(__name__)

# Context manager for operation tracking
class LogContext:
    def __init__(self, operation: str, **metadata):
        self.operation = operation
        self.metadata = metadata
    
    def __enter__(self):
        logger.info(
            f"Starting: {self.operation}",
            extra={"operation": self.operation, **self.metadata}
        )
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type:
            logger.error(
                f"Failed: {self.operation}",
                exc_info=(exc_type, exc_val, exc_tb),
                extra={"operation": self.operation, **self.metadata}
            )
        else:
            logger.info(
                f"Completed: {self.operation}",
                extra={"operation": self.operation, **self.metadata}
            )

# Usage
with LogContext("problem_solving", problem_id="prob_123"):
    await solve_problem(problem)
```

### Graceful Shutdown

```python
class HiveBot:
    async def shutdown(self, reason: str = "user_requested"):
        """Graceful shutdown with final checkpoint"""
        logging.info(f"Shutting down: {reason}")
        
        # Save final state
        await self.state_manager.save_checkpoint()
        
        # Close browser
        await self.browser_manager.close()
        
        # Summary
        summary = self.state_manager.get_progress()
        logging.info(
            f"Session complete: {summary.completed} solved, "
            f"{summary.failed} failed, {summary.total} total"
        )
```

---

## Design Rationale & Key Decisions

### Why Modular Component Structure?

**Decision**: Separate concerns into `browser/`, `auth/`, `hive/`, `editor/`, `solver/`, `state/`

**Rationale**:
- Each phase (1-7) can develop independently
- Editor adapters can be extended without touching solver code
- State management decoupled from UI logic
- Provider fallback strategy isolated in solver module
- Easier to test components in isolation
- Supports future refactoring (e.g., switching browser tech)

### Why Persistent Browser Profile?

**Decision**: Store Chrome profile on disk, reuse across runs

**Rationale**:
- Authentication persists → no re-login each run
- Hive Extension Detector state persists (security mechanism)
- Faster startup on subsequent runs
- Matches real user behavior (not anonymous mode)
- Enables crash recovery within same session

### Why Real Editor Integration, Not Copy-Paste?

**Decision**: Programmatically update editor via API, not textarea manipulation

**Rationale**:
- Editors maintain internal state (AST, formatting, validation)
- Copy-paste bypasses editor state → parse errors, lost metadata
- Programmatic insertion ensures editor recognizes changes
- Better for future features (code completion, hints, auto-format)
- More robust against editor UI changes

### Why Provider Abstraction & Fallback Chain?

**Decision**: Abstract AI provider interface with primary → secondary → tertiary fallback

**Rationale**:
- Protects against single provider outage
- Supports future providers (Ollama, Claude, etc.) without code changes
- Enables cost optimization (cheaper provider first, premium as fallback)
- Decouples prompt engineering from provider logistics
- Future: enable A/B testing of providers

### Why State Machine Over Imperative Loops?

**Decision**: Explicit state machine with validated transitions vs. nested loops

**Rationale**:
- Clear, visualizable workflow (reduces bugs)
- Crash recovery: can restore to exact prior state
- Enforces valid transitions (prevents invalid workflows)
- Easier to add observability hooks per state
- Simplifies testing (state transitions are testable)

### Why Checkpoint After Each Milestone?

**Decision**: Save state frequently (after login, problem fetch, submission, etc.)

**Rationale**:
- Crash at any point → resume from last checkpoint (no re-work)
- Minimizes wasted API calls (no duplicate generations)
- Auditable (can replay exact sequence of events)
- Enables manual recovery (user can inspect checkpoints)
- Low overhead (JSON file, atomic writes)

### Why Groq as Primary Provider?

**Decision**: Use Groq API as primary provider, with OpenAI/Gemini as fallbacks

**Rationale**:
- **Ultra-Low Latency**: Groq delivers 800+ tokens/sec vs 20-30 for OpenAI, ideal for retry loops
- **Cost-Effective**: $0.50-$1.50 per 1M tokens vs $10-30 for OpenAI, significant savings at scale
- **OpenAI-Compatible**: Drop-in replacement API, easy integration and migration
- **Perfect for Competitive Coding**: Fixed, predictable solutions benefit from faster inference
- **Fallback Chain**: OpenAI/Gemini ensure reliability if Groq is unavailable
- **Real-Time Suitability**: Fast turnaround enables responsive retry/debugging workflows

### Why Runtime Editor Detection vs. Hard-Coded?

**Decision**: Always detect editor at runtime, don't assume editor type

**Rationale**:
- **Platform Evolution**: Hive platform may change editor since design, detection ensures compatibility
- **Problem Variation**: Different problem categories might use different editors (web dev vs. competitive coding)
- **URL Flexibility**: Users may be on different Hive URLs or deployments with different setups
- **Graceful Fallback**: Robust fallback chain (Monaco → CodeMirror → Ace → Generic) ensures robustness
- **Resilience to Changes**: Makes bot more resilient to platform UI updates without code changes
- **Unknown Editors**: Enables graceful discovery of editor types not anticipated at design time
- **Robustness**: Generic adapter always available ensures bot never fails due to editor detection

---

## Future Extensibility

### Multi-Language Support

**Current**: C, C++, Java, Python

**Future**: Go, Rust, JavaScript, TypeScript, C#
- Prompt engineering adapts per language
- Editor language mode detection
- Validator rules per language

### Local AI Models via Ollama

**Phase 5+ enhancement**:
- Ollama provider stub exists (Phase 1)
- Phase 5: Implement Ollama provider
- No API key needed, full privacy
- Cost: 0 (runs locally)

### Advanced Retry Strategies

**Phase 6+ enhancement**:
- Parse error → extract root cause (e.g., off-by-one in loop)
- Semantic retry: "Fix the off-by-one error in loop"
- ML-based error classification (TLE vs. WA → different strategies)

### Multi-Problem Batching

**Phase 7** already supports:
- Process 50 problems sequentially
- Future: Parallel problem processing (if platform allows)
- Load balancing across AI providers

---

## Dependencies & Tech Stack

```
Python 3.10+
playwright>=1.40.0
pydantic>=2.0.0              # Config validation
pyyaml>=6.0.0                # Config files
openai>=1.0.0                # OpenAI provider
google-generativeai>=0.3.0   # Gemini provider
groq>=0.4.0                  # Groq API provider (ultra-fast)
pytest>=7.0.0                # Testing
pytest-asyncio>=0.21.0       # Async test support
aiofiles>=23.0.0             # Async file I/O
python-dotenv>=1.0.0         # Environment variables
```

---

## Success Metrics & Phase 1 Validation

### Phase 1 Validation Criteria

- [x] Browser launches with Chrome
- [x] Persistent profile created & persisted
- [x] Hive Extension detected and enabled
- [x] User successfully logs in
- [x] Problem list fetched and parsed
- [x] Problem metadata extracted (title, difficulty, etc.)
- [x] State checkpoints saved to disk
- [x] Recovery from checkpoint works
- [x] Logging captures full workflow
- [x] Graceful error handling with retries

### Overall Bot Success Metrics

- **Accuracy**: % of problems solved correctly (target: 80%+)
- **Completion Rate**: % of problems successfully submitted (target: 95%+)
- **Retry Efficiency**: Average attempts per problem (target: 1.5)
- **Speed**: Time per problem (depends on complexity, target: <2 min avg)
- **Uptime**: % of batch runs completed without crash (target: 99%+)

---

## Appendix: Technology Choices

| Choice | Alternative | Why |
|---|---|---|
| Playwright | Selenium | Better async support, better performance, more modern |
| Python | JavaScript/Node | Rich ML/AI library ecosystem, simple syntax, fast development |
| Persistent Profile | Anonymous Mode | Reduces login frequency, matches real user behavior |
| Provider Pattern | Hardcoded providers | Flexibility, future extensibility, testable |
| State Machine | Imperative loops | Visibility, crash recovery, enforced correctness |
| JSON State | SQLite/Database | Simple, human-readable, no external dep, easy versioning |
| Pydantic | dataclasses | Built-in validation, serialization, error messages |
| pytest | unittest | Better fixture support, cleaner syntax, wider ecosystem |

---

## Document Metadata

- **Version**: 1.0
- **Status**: Design Phase Complete, Ready for Phase 1 Implementation
- **Author**: Kiro AI
- **Last Updated**: 2024-01-15
- **Next Phase**: Phase 1 Implementation (Browser + Auth + Problem Discovery)

