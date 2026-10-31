// ps5key: ESP32-S3 on a PS5 USB port as a USB keyboard, driven over Wi-Fi by tools/ps5wake.py.
//
// First start (no Wi-Fi saved): opens the access point "ps5key-setup"; connect a phone, open http://192.168.4.1 and
// enter the home Wi-Fi. Saved in flash (Preferences), never in this source. Hold BOOT (GPIO0) at power-up to forget it.
//
// API (port 80, also http://ps5key.local):
//   GET /ping                  -> "ps5key ok <usb-mounted 0|1>"
//   GET /diag                  -> USB state and event counters (why a host does not take the keyboard)
//   GET /key?k=NAME            -> one key press (enter, esc, up, down, left, right, tab, space, home, end)
//   GET /seq?s=enter,!800,down -> keys in order; "!N" waits N ms (max 10 s per step)
// Board: "ESP32S3 Dev Module", USB Mode "USB-OTG (TinyUSB)" (set by the FQBN in tools/ps5wake.py flash).
#include <ESPmDNS.h>
#include <Preferences.h>
#include <USB.h>
#include <USBHIDKeyboard.h>
#include <WebServer.h>
#include <ArduinoOTA.h>
#include <WiFi.h>

USBHIDKeyboard kb;
WebServer web(80);
Preferences prefs;
bool usb_mounted = false;
uint32_t usb_events[8] = {0};  // count per arduino_usb_event_t (started, stopped, suspend, resume, ...)
extern "C" bool tud_mounted(void);
extern "C" bool tud_suspended(void);

static int key_code(const String& k) {
  if (k == "enter") return KEY_RETURN;
  if (k == "esc") return KEY_ESC;
  if (k == "up") return KEY_UP_ARROW;
  if (k == "down") return KEY_DOWN_ARROW;
  if (k == "left") return KEY_LEFT_ARROW;
  if (k == "right") return KEY_RIGHT_ARROW;
  if (k == "tab") return KEY_TAB;
  if (k == "space") return ' ';
  if (k == "home") return KEY_HOME;
  if (k == "end") return KEY_END;
  return -1;
}

static bool press(const String& k) {
  int c = key_code(k);
  if (c < 0) return false;
  kb.press(c);
  delay(80);  // the PS5 UI misses taps shorter than a frame or two
  kb.releaseAll();
  delay(120);
  return true;
}

static void handle_key() {
  String k = web.arg("k");
  if (!press(k)) return web.send(400, "text/plain", "unknown key " + k);
  web.send(200, "text/plain", "ok");
}

static void handle_seq() {
  String s = web.arg("s") + ",";
  int start = 0;
  for (int i = s.indexOf(','); i >= 0; start = i + 1, i = s.indexOf(',', start)) {
    String step = s.substring(start, i);
    step.trim();
    if (step.isEmpty()) continue;
    if (step[0] == '!') {
      delay(constrain(step.substring(1).toInt(), 0, 10000));
    } else if (!press(step)) {
      return web.send(400, "text/plain", "unknown key " + step);
    }
  }
  web.send(200, "text/plain", "ok");
}

static void setup_portal() {
  WiFi.mode(WIFI_AP);
  WiFi.softAP("ps5key-setup");
  web.on("/", [] {
    web.send(200, "text/html",
             "<meta name=viewport content='width=device-width'><h3>ps5key Wi-Fi</h3>"
             "<form method=post action=/save>SSID<br><input name=s><br>Password<br><input name=p type=password><br>"
             "<button>Save</button></form>");
  });
  web.on("/save", HTTP_POST, [] {
    prefs.putString("ssid", web.arg("s"));
    prefs.putString("pass", web.arg("p"));
    web.send(200, "text/plain", "saved, restarting");
    delay(500);
    ESP.restart();
  });
  web.begin();
  for (;;) web.handleClient();
}

void setup() {
  USB.onEvent([](void*, esp_event_base_t, int32_t id, void*) {
    if (id >= 0 && id < 8) ++usb_events[id];
    if (id == ARDUINO_USB_STARTED_EVENT) usb_mounted = true;
    if (id == ARDUINO_USB_STOPPED_EVENT) usb_mounted = false;
  });
  kb.begin();
  USB.begin();
  prefs.begin("ps5key", false);
  pinMode(0, INPUT_PULLUP);
  if (digitalRead(0) == LOW) prefs.clear();  // BOOT held at power-up: forget the Wi-Fi
  String ssid = prefs.getString("ssid", "");
  if (ssid.isEmpty()) setup_portal();
  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);  // a sleeping radio misses the first request
  WiFi.begin(ssid.c_str(), prefs.getString("pass", "").c_str());
  for (int i = 0; i < 60 && WiFi.status() != WL_CONNECTED; ++i) delay(500);
  if (WiFi.status() != WL_CONNECTED) setup_portal();  // wrong password or network gone: let the user fix it
  MDNS.begin("ps5key");
  web.on("/ping", [] { web.send(200, "text/plain", String("ps5key ok ") + (tud_mounted() ? "1" : "0")); });
  web.on("/diag", [] {
    String r = String("mounted=") + tud_mounted() + " suspended=" + tud_suspended() + " event_flag=" + usb_mounted + " events=";
    for (uint32_t n : usb_events) r += String(n) + ",";
    web.send(200, "text/plain", r + " rssi=" + WiFi.RSSI() + " up_s=" + millis() / 1000);
  });
  ArduinoOTA.setHostname("ps5key");  // later updates: tools/ps5wake.py flash --ota (no BOOT button, no unplugging)
  ArduinoOTA.begin();
  web.on("/key", handle_key);
  web.on("/seq", handle_seq);
  web.begin();
}

void loop() {
  web.handleClient();
  ArduinoOTA.handle();
  static uint32_t last_try = 0;
  if (WiFi.status() != WL_CONNECTED && millis() - last_try > 10000) {
    last_try = millis();
    WiFi.reconnect();
  }
}
