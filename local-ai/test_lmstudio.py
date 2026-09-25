from lmstudio_client import MODEL, chat, list_models

def main() -> int:
    print("Dashboard Factory — LM Studio test")
    print(f"Expected model: {MODEL}\n")
    try:
        models = list_models()
    except Exception as exc:
        print("✗ Cannot reach LM Studio")
        print(exc)
        print("Check that LM Studio is running and Developer → Start Server is ON.")
        return 1
    print("✓ LM Studio reachable")
    for m in models: print(f"  - {m}")
    if MODEL not in models:
        print(f"\n⚠ Model '{MODEL}' is not exposed. Load it in LM Studio first.")
        return 2
    try:
      answer = chat(
    [
        {
            "role": "system",
            "content": "You are a concise dashboard analytics assistant."
        },
        {
            "role": "user",
            "content": "/no_think Reply with exactly: LOCAL_AI_OK"
        }
    ],
    temperature=0,
    max_tokens=128,
        )
    except Exception as exc:
        print("✗ Model request failed")
        print(exc)
        return 3
    print("✓ Local AI response received")
    print("  Response:", answer.strip())
    return 0

if __name__ == "__main__": raise SystemExit(main())
