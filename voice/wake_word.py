from voice.voice_input import listen_offline

WAKE_WORD = "hey revela"


def wait_for_wake_word():
    print("🟢 Waiting for wake word: 'Hey Revela'")

    while True:
        text = listen_offline(timeout=3)
        if not text:
            continue

        print("Heard:", text)

        if WAKE_WORD in text.lower():
            print("✅ Wake word detected")
            return
