import os, json, subprocess, threading, requests, socket, queue, time, difflib
import pyttsx3, pyaudio, numpy as np
import speech_recognition as sr
from dotenv import load_dotenv
from datetime import datetime
import pygame, tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext
import wikipedia

load_dotenv()
SERP_API_KEY = os.getenv("77dda849533cd492755ec41bada5648a3ba0ad2272821ee1b66fab06c50bb1c9")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
DEESEEK_API_KEY = os.getenv("DEESEEK_API_KEY")
JARVIS_UPDATE_URL = os.getenv("JARVIS_UPDATE_URL")

engine = pyttsx3.init()
engine.setProperty("rate", 185)
engine.setProperty("voice", engine.getProperty("voices")[0].id)
USER_NAME = "Simon Peter"

recognizer = sr.Recognizer()
mic = sr.Microphone()
q = queue.Queue()
MIN_COMMAND_LENGTH = 2
last_fallback_time = 0
fallback_cooldown = 10
WAKE_WORDS = ["jarvis", "boss"]
SEARCH_KEYWORDS = [
    "search", "who is", "what is", "tell me", "define", "explain",
    "how to", "how does", "what happens", "information about", "give me details on",
    "where is", "when did", "history of", "describe", "why is", "guide me on",
    "tutorial on", "lookup", "translate", "convert", "meaning of", "example of",
    "facts about", "news on", "data about", "science behind", "working of",
    "benefits of", "drawbacks of", "importance of", "latest on", "update on",
    "background of", "purpose of", "process of", "reason for", "story of","new about","Pakistan new","latest world new"
]
COMMAND_KEYWORDS = ["open", "launch", "run", "execute"]

MEMORY_FILE, LOG_FILE = "command_memory.json", "session_log.txt"
SESSION_LOG = []
custom_commands = json.load(open(MEMORY_FILE)) if os.path.exists(MEMORY_FILE) else {}

CACHE_FILE = "answer_cache.json"
answer_cache = json.load(open(CACHE_FILE)) if os.path.exists(CACHE_FILE) else {}

root = tk.Tk()
root.title("Jarvis Control Panel")
root.geometry("600x450")
log_text = scrolledtext.ScrolledText(root, wrap=tk.WORD, bg="black", fg="lime", font=("Consolas", 10))
log_text.pack(expand=True, fill='both')

confidence_label = tk.Label(root, text="Confidence: ", fg="white", bg="black", anchor='w')
confidence_label.pack(fill='x')

sensitivity_scale = tk.Scale(root, from_=0, to=100, orient='horizontal', label="Matching Sensitivity", bg='black', fg='white')
sensitivity_scale.set(60)
sensitivity_scale.pack(fill='x')

stop_speaking = threading.Event()

def log_gui(message):
    if "listening timed out" in message.lower():
        return
    log_text.insert(tk.END, f"{message}\n")
    log_text.see(tk.END)

def speak(text):
    print(f"Jarvis: {text}")
    log_gui(f"\n🧠 Jarvis: {text}\n")
    try:
        def monitor_stop():
            stop_speaking.clear()
            while engine._inLoop:
                cmd = listen_for_voice_command()
                if cmd and "stop" in cmd.lower():
                    stop_speaking.set()
                    engine.stop()
                    break
        threading.Thread(target=monitor_stop, daemon=True).start()
        engine.say(f"Sir, {text}")
        engine.runAndWait()
    except:
        pass

# ... rest of the code remains unchanged

def log_session(entry):
    with open(LOG_FILE, 'a') as f:
        f.write(f"{datetime.now()}: {entry}\n")

def check_internet():
    try:
        socket.create_connection(("1.1.1.1", 53), timeout=3)
        return True
    except:
        return False

def is_search_query(text):
    text = text.lower()
    return any(text.startswith(k) or k in text for k in SEARCH_KEYWORDS)

def is_command_request(text):
    return any(text.startswith(k) for k in COMMAND_KEYWORDS)

def normalize_command(text):
    for k in COMMAND_KEYWORDS:
        if text.startswith(k):
            return text.replace(k, "", 1).strip()
    return text

def fuzzy_match_command(input_text):
    if not custom_commands:
        return None
    raw_input = input_text.strip().lower()
    norm_input = normalize_command(raw_input)
    cutoff = sensitivity_scale.get() / 100.0
    all_keys = list(map(str.lower, custom_commands.keys()))

    for attempt in [raw_input, norm_input]:
        matches = difflib.get_close_matches(attempt, all_keys, n=1, cutoff=cutoff)
        if matches:
            for k in custom_commands:
                if k.lower() == matches[0]:
                    confidence_label.config(text=f"Confidence: {round(cutoff*100)}% match for '{k}'")
                    return k

    confidence_label.config(text="Confidence: No good match found")
    return None

def learn_command(command):
    speak(f"Sir, I don’t recognize '{command}'. Should I learn it?")
    confirmation = listen_for_voice_command()
    if confirmation in ["yes", "sure", "ok","yes sure", "yes please","go save","save please","yes save it"]:
        root.withdraw()
        path = filedialog.askopenfilename(title=f"Select file for '{command}'")
        root.deiconify()
        if path:
            custom_commands[command] = path
            with open(MEMORY_FILE, 'w') as f:
                json.dump(custom_commands, f, indent=4)
            speak(f"Learned and saved command '{command}'.")
        else:
            speak("No file selected. Command not saved.")
    else:
        speak("Okay, not learning this command.")

def fallback_answer(query):
    global last_fallback_time
    if query in answer_cache:
        return f"Previously found, Sir: {answer_cache[query]}"
    try:
        answer = call_serpapi(query)
        if not answer:
            summary = wikipedia.summary(query, sentences=2)
            if summary:
                answer_cache[query] = summary
                with open(CACHE_FILE, 'w') as f:
                    json.dump(answer_cache, f, indent=2)
                return f"Here's a summary I found, Sir: {summary}"
        if answer and isinstance(answer, str) and len(answer.strip()) > 2:
            summary = answer.strip().split(".")[0].strip()
            answer_cache[query] = summary
            with open(CACHE_FILE, 'w') as f:
                json.dump(answer_cache, f, indent=2)
            return f"Here's what I found, Sir: {summary}"
    except Exception as e:
        log_gui(f"[Fallback Error] {e}")
    if time.time() - last_fallback_time > fallback_cooldown:
        last_fallback_time = time.time()
        return "Despite checking multiple databases, Sir, I couldn't retrieve useful information."
    return ""

def listen_for_voice_command():
    try:
        with mic as source:
            recognizer.adjust_for_ambient_noise(source, duration=0.05)
            audio = recognizer.listen(source, timeout=1.4, phrase_time_limit=4.5)
        final = recognizer.recognize_google(audio).lower().strip() if check_internet() else recognizer.recognize_sphinx(audio).lower().strip()
        if len(final) >= MIN_COMMAND_LENGTH:
            log_gui(f"you said: {final}")
            return final
    except:
        return ""
    return ""

def listen_for_wake_word():
    while True:
        trigger = listen_for_voice_command()
        if trigger and any(w in trigger for w in WAKE_WORDS):
            return

def call_serpapi(q):
    try:
        url = f"https://serpapi.com/search.json?q={q}&api_key={SERP_API_KEY}"
        headers = {"User-Agent": "Mozilla/5.0"}
        data = requests.get(url, headers=headers).json()

        if "answer_box" in data and data["answer_box"]:
            ab = data["answer_box"]
            return ab.get("answer") or ab.get("snippet") or ab.get("title")

        if "knowledge_graph" in data and data["knowledge_graph"]:
            kg = data["knowledge_graph"]
            return kg.get("description") or kg.get("title")

        results = data.get("organic_results", [])
        for item in results:
            if item.get("snippet"):
                return item["snippet"]

        return None
    except Exception as e:
        log_gui(f"[SerpAPI Error] {str(e)}")
        return None

def system_command_handler(cmd):
    if cmd in ["shutdown", "turn off"]:
        speak("Shutting down your system.")
        os.system("shutdown /s /t 1")
    elif cmd in ["restart", "reboot"]:
        speak("Restarting your system.")
        os.system("shutdown /r /t 1")
    elif cmd in ["sleep", "go to sleep"]:
        speak("Putting system to sleep.")
        os.system("rundll32.exe powrprof.dll,SetSuspendState 0,1,0")
    elif cmd == "enable wifi":
        subprocess.call("netsh interface set interface 'Wi-Fi' enable", shell=True)
        speak("Wi-Fi enabled.")
    elif cmd == "disable wifi":
        subprocess.call("netsh interface set interface 'Wi-Fi' disable", shell=True)
        speak("Wi-Fi disabled.")
    elif cmd == "enable bluetooth":
        subprocess.call('powershell "Start-Service bthserv"', shell=True)
        speak("Bluetooth enabled.")
    elif cmd == "disable bluetooth":
        subprocess.call('powershell "Stop-Service bthserv"', shell=True)
        speak("Bluetooth disabled.")
    else:
        return False
    return True

def auto_update():
    if not JARVIS_UPDATE_URL:
        return
    try:
        r = requests.get(JARVIS_UPDATE_URL)
        if r.status_code == 200:
            with open(__file__, 'wb') as f:
                f.write(r.content)
            speak("Update downloaded. Please restart.")
    except:
        speak("Update failed.")

def main():
    auto_update()
    speak(f"Greetings {USER_NAME}. I am J.A.R.V.I.S. Online and ready.")
    speak("Say 'Jarvis' or 'Boss' to begin.")
    while True:
        listen_for_wake_word()
        speak("Listening...")
        time.sleep(0.3)
        command = listen_for_voice_command()
        if not command:
            continue
        if command in ["exit", "quit", "bye"]:
            speak("Goodbye Sir. Shutting down.")
            break
        log_session(command)
        normalized = normalize_command(command)

        if system_command_handler(normalized):
            continue

        match = fuzzy_match_command(command) or fuzzy_match_command(normalized)
        if match:
            subprocess.Popen(custom_commands[match], shell=True)
            speak(f"Running saved command for '{match}'.")
            continue

        if is_command_request(command):
            learn_command(normalized)
            continue

        elif is_search_query(command):
            if check_internet():
                response = fallback_answer(command)
                if response:
                    speak(response)
                else:
                    speak("Sir, I scoured my databases but couldn't extract anything relevant.")
            else:
                speak("You're offline. I can't search right now.")
        else:
            speak("I'm afraid I didn't catch that, Sir.")

if __name__ == "__main__":
    threading.Thread(target=main).start()
    root.mainloop()
