import requests

STREAMLIT_APP_URL = "https://digital-portfolio-web.streamlit.app"

def main():
    try:
        r = requests.get(STREAMLIT_APP_URL, timeout=30)
        print(f"Keep-alive ping OK: {r.status_code}")
    except Exception as e:
        print(f"Keep-alive ping FAILED: {e}")

if __name__ == "__main__":
    main()