import os
import time
import json
import math
import requests
import subprocess
from dotenv import load_dotenv
from google import genai
from google.genai import types

# Load environment variables from .env file
load_dotenv()


class SentinelObserver:
    def __init__(self):
        self.prometheus_url = os.getenv(
            "PROMETHEUS_URL", "http://localhost:9090")
        self.gemini_api_key = os.getenv("GEMINI_API_KEY")
        self.lm_studio_url = os.getenv(
            "LM_STUDIO_URL", "http://localhost:1234/api/v1/chat")

        # Thresholds
        self.cpu_threshold = float(os.getenv("CPU_THRESHOLD", "0.5"))
        self.latency_threshold = float(
            os.getenv("LATENCY_THRESHOLD", "2.0"))  # 2 seconds

        # Fallback chain of models
        self.models = [
            {"type": "gemini", "name": "gemini-2.5-flash"},
            {"type": "local", "name": "mistralai/ministral-3-3b"},
            {"type": "local", "name": "liquid/lfm2.5-1.2b"},
            {"type": "local", "name": "qwen/qwen3-vl-4b"}
        ]

    def query_prometheus(self, query):
        """Query Prometheus for a metric."""
        try:
            response = requests.get(
                f"{self.prometheus_url}/api/v1/query",
                params={"query": query},
                timeout=10
            )
            response.raise_for_status()
            data = response.json()
            if data.get('status') == 'success' and data['data']['result']:
                return float(data['data']['result'][0]['value'][1])
            return 0.0
        except requests.exceptions.RequestException as e:
            print(f"[ERROR] Prometheus unreachable or query failed: {e}")
            return None

    def fetch_container_logs(self, container_name="sentinel-target-api", lines=20):
        """Fetch the last N lines of logs from a Docker container."""
        try:
            result = subprocess.run(
                ["docker", "logs", "--tail", str(lines), container_name],
                capture_output=True,
                text=True,
                check=True
            )
            return result.stdout
        except subprocess.CalledProcessError as e:
            print(f"[WARNING] Could not fetch logs for {container_name}: {e}")
            return "Logs unavailable."
        except FileNotFoundError:
            print("[WARNING] Docker command not found.")
            return "Docker not installed or unavailable."

    def analyze_with_ai(self, metrics_data, logs):
        """Send metrics and logs to AI models for Root Cause Analysis."""
        system_prompt = (
            "You are a Senior Site Reliability Engineer. Analyze the following metrics and logs from a FastAPI service. "
            "Respond ONLY with a valid JSON object containing the following keys: "
            "'root_cause' (string: What happened?), "
            "'severity' (string: Low/Medium/High/Critical), "
            "'remediation_step' (string: What command should I run to fix this? e.g., 'docker-compose restart')."
        )

        input_prompt = f"Metrics:\n{json.dumps(metrics_data, indent=2)}\n\nLogs:\n{logs}"

        for model_info in self.models:
            print(
                f"[*] Attempting analysis with model: {model_info['name']} ({model_info['type']})")
            try:
                if model_info['type'] == 'gemini':
                    if not self.gemini_api_key:
                        print("[-] Gemini API key not set, skipping...")
                        continue

                    client = genai.Client(api_key=self.gemini_api_key)
                    response = client.models.generate_content(
                        model=model_info['name'],
                        contents=f"{system_prompt}\n\n{input_prompt}",
                        config=types.GenerateContentConfig(
                            response_mime_type="application/json",
                        )
                    )
                    return self._parse_ai_response(response.text, model_info['name'])

                elif model_info['type'] == 'local':
                    payload = {
                        "model": model_info['name'],
                        "system_prompt": system_prompt,
                        "input": input_prompt
                    }
                    response = requests.post(
                        self.lm_studio_url,
                        headers={"Content-Type": "application/json"},
                        json=payload,
                        timeout=30
                    )
                    response.raise_for_status()

                    resp_json = response.json()
                    ai_text = ""

                    # Handle different possible response structures from local API
                    if "choices" in resp_json and len(resp_json["choices"]) > 0:
                        ai_text = resp_json["choices"][0].get(
                            "message", {}).get("content", "")
                    elif "response" in resp_json:
                        ai_text = resp_json["response"]
                    elif "message" in resp_json:
                        ai_text = resp_json["message"]
                    else:
                        ai_text = str(resp_json)

                    return self._parse_ai_response(ai_text, model_info['name'])

            except Exception as e:
                print(
                    f"[!] Model {model_info['name']} failed: {e}. Trying next model...")

        return {"error": "All models failed to provide an analysis."}

    def _parse_ai_response(self, text, model_name):
        """Parse the AI response text into a JSON object."""
        try:
            # Try to extract JSON if it's wrapped in markdown blocks
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0].strip()
            elif "```" in text:
                text = text.split("```")[1].split("```")[0].strip()

            data = json.loads(text)
            data['model_used'] = model_name
            return data
        except json.JSONDecodeError:
            return {
                "root_cause": "Failed to parse AI response as JSON.",
                "severity": "Unknown",
                "remediation_step": "Manual investigation required.",
                "raw_response": text,
                "model_used": model_name
            }

    def print_diagnosis(self, diagnosis):
        """Print the AI diagnosis in a clean, readable format."""
        print("\n" + "="*60)
        print("🤖 AI DIAGNOSIS REPORT")
        print("="*60)
        print(f"Model Used       : {diagnosis.get('model_used', 'N/A')}")
        print(f"Severity         : {diagnosis.get('severity', 'N/A')}")
        print(f"Root Cause       : {diagnosis.get('root_cause', 'N/A')}")
        print(f"Remediation Step : {diagnosis.get('remediation_step', 'N/A')}")
        if 'raw_response' in diagnosis:
            print(f"Raw Response     : {diagnosis.get('raw_response')}")
        if 'error' in diagnosis:
            print(f"Error            : {diagnosis.get('error')}")
        print("="*60 + "\n")

    def execute_remediation(self, command: str):
        """Execute authorized system commands to heal the target API."""
        ALLOWED_COMMANDS = [
            'docker-compose restart',
            'docker-compose stop',
            'docker-compose up -d',
            'docker restart sentinel-target-api',
            'docker stop sentinel-target-api'
        ]

        if command not in ALLOWED_COMMANDS:
            print(
                f"[WARNING] Command '{command}' is not in the allowed whitelist. Skipping execution.")
            return False

        print(f"\n[!] WARNING: About to execute system command: {command}")
        print(f"[*] AI-Suggested Action: Executing {command}...")

        try:
            # Split the command into a list to avoid shell=True
            cmd_list = command.split()
            result = subprocess.run(
                cmd_list, capture_output=True, text=True, check=True)
            print(f"[*] Command executed successfully.")

            # Wait 30 seconds and check health
            print("[*] Waiting 30 seconds for the service to stabilize...")
            time.sleep(30)

            health_url = "http://localhost:8000/health"
            try:
                response = requests.get(health_url, timeout=5)
                if response.status_code == 200:
                    print("[+] Healing was successful! The service is healthy.")
                    return True
                else:
                    print(
                        f"[-] Healing failed. Health check returned status code: {response.status_code}. Manual intervention is still required.")
                    return False
            except requests.exceptions.RequestException as e:
                print(
                    f"[-] Healing failed. Could not reach health endpoint: {e}. Manual intervention is still required.")
                return False

        except subprocess.CalledProcessError as e:
            print(f"[ERROR] Command execution failed: {e}")
            print(f"Output: {e.stderr}")
            return False
        except FileNotFoundError:
            print(
                "[ERROR] Command not found. Ensure docker/docker-compose is installed.")
            return False

    def monitor(self):
        """Main loop to poll Prometheus and trigger AI analysis on anomalies."""
        print(f"Starting SentinelObserver... Polling every 30 seconds.")
        print(
            f"Thresholds - CPU: {self.cpu_threshold}, Latency: {self.latency_threshold}s")

        while True:
            cpu_usage = self.query_prometheus(
                'rate(process_cpu_seconds_total[1m])')

            # Query the 90th percentile latency over the last 1 minute
            latency_query = 'histogram_quantile(0.90, sum(rate(http_request_duration_seconds_bucket[1m])) by (le))'
            latency = self.query_prometheus(latency_query)

            if cpu_usage is None or latency is None:
                time.sleep(30)
                continue

            # Handle NaN from Prometheus if there are no requests
            if math.isnan(latency):
                latency = 0.0

            print(
                f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] CPU: {cpu_usage:.4f}, P90 Latency: {latency:.2f}s")

            if cpu_usage > self.cpu_threshold or latency > self.latency_threshold:
                print(
                    "\n[!] Anomalous activity detected. Consulting Gemini/Local AI...")

                metrics_data = {
                    "cpu_usage_rate_1m": cpu_usage,
                    "p90_latency_1m": latency,
                    "cpu_threshold": self.cpu_threshold,
                    "latency_threshold": self.latency_threshold
                }

                logs = self.fetch_container_logs()
                diagnosis = self.analyze_with_ai(metrics_data, logs)
                self.print_diagnosis(diagnosis)

                # Action Layer: Auto-remediation for High/Critical severity
                severity = diagnosis.get('severity', '').lower()
                if severity in ['high', 'critical']:
                    remediation_step = diagnosis.get('remediation_step')
                    if remediation_step and remediation_step != 'N/A':
                        self.execute_remediation(remediation_step)

                # Sleep longer after an anomaly to prevent spamming
                print("Sleeping for 60 seconds after anomaly detection...")
                time.sleep(60)
            else:
                time.sleep(30)


if __name__ == "__main__":
    observer = SentinelObserver()
    observer.monitor()
