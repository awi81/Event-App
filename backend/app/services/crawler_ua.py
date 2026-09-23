"""One honest, identifiable User-Agent for every crawler request.

Sites see who is fetching and how to reach us, and can block us if they want
to. Posing as a browser to get past a block is what this project does not do
(wasgehtapp and Rausgegangen were dropped for exactly that reason).
"""
import os

CRAWLER_CONTACT = os.getenv("NOMINATIM_CONTACT", "your-email@example.com")
CRAWLER_USER_AGENT = f"Event-App-Essen/1.0 (+{CRAWLER_CONTACT})"
