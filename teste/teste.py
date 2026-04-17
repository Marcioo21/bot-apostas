from google import genai
import sys

# Your API key
CHAVE_API = "AIzaSyCLOkqf7jrVWOHOoT2flkhkohbbD8l1bh4"

# Initialize the new client
client = genai.Client(api_key=CHAVE_API)

print("--- 🤖 Chat com Gemini (Nova SDK) ---")
print("(Digite 'sair' para encerrar)")

# Conversation history
chat_session = []

while True:
    try:
        prompt = input("\nVocê: ").strip()
        
        if not prompt:
            continue
            
        if prompt.lower() in ["sair", "exit", "quit"]:
            break

        # Send the message using the new format
        response = client.models.generate_content(
            model="gemini-1.5-flash",
            contents=prompt
        )
        
        print(f"\nGemini: {response.text}")
        
    except KeyboardInterrupt:
        break
    except Exception as e:
        print(f"\nErro: {e}")

print("\nAté logo!")
