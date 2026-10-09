"""Prozessweite Sperre für ressourcenintensive KI-Modell-Inferenz."""
import threading

inference_lock = threading.Lock()
