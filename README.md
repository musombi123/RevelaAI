# RevelaAI 🧠📖  
**A Philosophical & Theological AI Assistant**

RevelaAI is an AI-powered assistant designed to help users explore, compare, and understand **theology, philosophy, prophecy, and scripture** across multiple traditions — neutrally, transparently, and responsibly.

It integrates modern Large Language Models (LLMs) with structured reasoning to analyze sacred texts, prophecies, and theological concepts while clearly distinguishing **interpretation**, **tradition**, and **historical status**.

---

## ✨ Core Features

### 🧠 Theological Intelligence
- Christianity (Bible – OT & NT)
- Islam (Qur’an & Hadith references)
- Hinduism (Vedas, Upanishads, Bhagavad Gita)
- Judaism (Tanakh references)
- Traditional & philosophical belief systems

---

### 📖 Scripture Analysis
- Verse-by-verse explanations  
- Neutral interpretation across traditions  
- Direct scripture quotations  
- Cross-textual comparisons  

Example:
> *“Explain Revelation 3:21 verse by verse”*

---

### 🔍 Prophecy Evaluation Engine
- Identifies prophetic statements
- Explains traditional interpretations
- Assesses **status**:
  - Fulfilled
  - Partially fulfilled
  - Unfulfilled
  - Symbolic / debated
- Clearly labels speculation vs doctrine

---

### 📚 Source Transparency
- Explicit scripture citations (Book, Chapter, Verse)
- Source IDs for traceability
- No hidden authority claims

---

### 🌐 Philosophical Neutrality
- No preaching
- No forced belief systems
- Compares viewpoints side-by-side
- Encourages understanding, not persuasion

---

## 🏗️ Architecture Overview
RevelaAI/
│
├── ai/                  # Core AI orchestration modules
│   ├── ai_client/       # Handles LLM/GROQ/Replicate clients
│   ├── intent_router.py # Detects user intents to route queries
│   └── system_prompt.py # Centralized prompts for AI reasoning
│
├── config/              # Configuration files and environment settings
├── core/                # Core application logic and helpers
├── db/                  # MongoDB connectors & collection setups
├── features/            # Modular features like emotional intelligence, creativity, decision-making
├── models/              # AI/ML models, tokenizers, embeddings
├── routes/              # Flask Blueprints for API endpoints
├── services/            # Business logic: AI processing, RSS fetching, expert modules
├── schemas/             # JSON schemas for consistent API responses
├── utils/               # Utility scripts (docx extraction, JSON helpers, etc.)
├── voice/               # Text-to-speech & speech-to-text services
│
├── app.py               # Main Flask application
└── predict.py           # Script for standalone AI predictions

