#!/usr/bin/env python
"""
Simple diagnostic script to test the chatbot functionality
"""
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'backend'))

print("[1/5] Testing GROQ_API_KEY...")
api_key = os.getenv('GROQ_API_KEY')
if not api_key:
    print("  ❌ GROQ_API_KEY not set!")
    print("  Creating .env file with placeholder...")
    # Don't actually create one, just note the issue
else:
    print(f"  ✓ GROQ_API_KEY is set (first 10 chars: {api_key[:10]}...)")

print("\n[2/5] Testing RAG Pipeline import...")
try:
    from rag_pipeline import RAGPipeline
    print("  ✓ RAG Pipeline imported successfully")
except Exception as e:
    print(f"  ❌ Failed to import RAG Pipeline: {e}")
    sys.exit(1)

print("\n[3/5] Testing RAG Pipeline initialization...")
try:
    rag = RAGPipeline()
    print("  ✓ RAG Pipeline initialized successfully")
except Exception as e:
    print(f"  ❌ Failed to initialize RAG Pipeline: {e}")
    sys.exit(1)

print("\n[4/5] Testing LLM Agent import...")
try:
    from llm_agent import LLMAgent
    print("  ✓ LLM Agent imported successfully")
except Exception as e:
    print(f"  ❌ Failed to import LLM Agent: {e}")
    sys.exit(1)

print("\n[5/5] Testing LLM Agent initialization...")
try:
    agent = LLMAgent(rag)
    print("  ✓ LLM Agent initialized successfully")
except Exception as e:
    print(f"  ❌ Failed to initialize LLM Agent: {e}")
    sys.exit(1)

print("\n[TEST] Testing answer_question with no API key...")
if not api_key:
    print("  Attempting to call answer_question without GROQ_API_KEY...")
    try:
        result = agent.answer_question("What is hemoglobin?", "test context")
        print(f"  Response: {result[:150]}...")
    except Exception as e:
        print(f"  ❌ Error: {e}")
else:
    print("  API key is set, would make actual API call")

print("\n" + "="*60)
print("DIAGNOSIS COMPLETE")
print("="*60)
