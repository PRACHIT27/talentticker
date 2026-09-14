"""The list of skills the ticker tracks.

Each entry is a canonical name mapped to the ways companies actually write it.
Keeping aliases explicit means "K8s", "Kubernetes" and "EKS" roll up to one
line on the ticker instead of three.

This dictionary catches the skills we already know about. Anything new and
unnamed is caught separately by the phrase miner in emerging.py.
"""
from __future__ import annotations

from pathlib import Path

# canonical name -> (category, [aliases])
SKILLS: dict[str, tuple[str, list[str]]] = {
    # ---------- languages ----------
    "Python": ("language", ["python", "python3"]),
    "Java": ("language", ["java"]),
    "JavaScript": ("language", ["javascript", "js", "es6", "ecmascript"]),
    "TypeScript": ("language", ["typescript", "ts"]),
    "Go": ("language", ["golang", "go programming", "go lang"]),
    "Rust": ("language", ["rust", "rustlang"]),
    "C++": ("language", [r"(?<!\w)c\+\+", "cpp"]),
    # A bare "C" is everywhere in English text, so only count it when it sits in
    # a list of languages ("C, C++, Rust") or is named as a language outright.
    "C": ("language", [r"(?<![\w+#])c(?=\s*(?:,|/|\||\)|;)|\s+(?:and|or)\s|"
                       r"\s+(?:programming|language))"]),
    "C#": ("language", ["c#", r"\bc\s?sharp\b"]),
    "Ruby": ("language", ["ruby"]),
    "PHP": ("language", ["php"]),
    "Swift": ("language", ["swift"]),
    "Kotlin": ("language", ["kotlin"]),
    "Scala": ("language", ["scala"]),
    "R": ("language", [r"\br\b(?=\s*(?:,|and|or|\)|programming|language))"]),
    "SQL": ("language", ["sql"]),
    "Bash": ("language", ["bash", "shell scripting", "zsh"]),
    "Perl": ("language", ["perl"]),
    "Elixir": ("language", ["elixir"]),
    "Haskell": ("language", ["haskell"]),
    "Clojure": ("language", ["clojure"]),
    "Objective-C": ("language", ["objective-c", "objective c"]),
    "MATLAB": ("language", ["matlab"]),
    "Solidity": ("language", ["solidity"]),
    "Zig": ("language", ["zig"]),
    "Mojo": ("language", ["mojo"]),

    # ---------- frontend ----------
    "React": ("frontend", ["react", "react.js", "reactjs"]),
    "Next.js": ("frontend", ["next.js", "nextjs"]),
    "Vue": ("frontend", ["vue", "vue.js", "vuejs"]),
    "Angular": ("frontend", ["angular", "angularjs"]),
    "Svelte": ("frontend", ["svelte", "sveltekit"]),
    "HTML/CSS": ("frontend", ["html", "css", "html5", "css3"]),
    "Tailwind": ("frontend", ["tailwind", "tailwindcss"]),
    "Redux": ("frontend", ["redux"]),
    "Webpack": ("frontend", ["webpack", "vite", "esbuild"]),
    "React Native": ("frontend", ["react native"]),
    "Flutter": ("frontend", ["flutter"]),
    "SwiftUI": ("frontend", ["swiftui"]),
    "Jetpack Compose": ("frontend", ["jetpack compose"]),
    "WebAssembly": ("frontend", ["webassembly", "wasm"]),
    "Accessibility": ("frontend", ["accessibility", "wcag", "a11y"]),

    # ---------- backend frameworks ----------
    "Node.js": ("backend", ["node.js", "nodejs", r"node\b"]),
    "Django": ("backend", ["django"]),
    "Flask": ("backend", ["flask"]),
    "FastAPI": ("backend", ["fastapi"]),
    "Spring": ("backend", ["spring boot", "spring framework", "springboot", "spring"]),
    "Rails": ("backend", ["ruby on rails", "rails"]),
    ".NET": ("backend", [r"\.net\b", "dotnet", "asp.net"]),
    "Express": ("backend", ["express.js", "expressjs", "express"]),
    "GraphQL": ("backend", ["graphql", "apollo"]),
    "gRPC": ("backend", ["grpc", "protobuf", "protocol buffers"]),
    "REST APIs": ("backend", ["rest api", "restful", "rest services", "rest"]),
    "Microservices": ("backend", ["microservice", "microservices"]),
    "WebSockets": ("backend", ["websocket", "websockets"]),

    # ---------- cloud ----------
    "AWS": ("cloud", ["aws", "amazon web services"]),
    "GCP": ("cloud", ["gcp", "google cloud"]),
    "Azure": ("cloud", ["azure"]),
    "Lambda": ("cloud", ["aws lambda", "lambda functions"]),
    "S3": ("cloud", [r"\bs3\b"]),
    "EC2": ("cloud", [r"\bec2\b"]),
    "DynamoDB": ("cloud", ["dynamodb"]),
    "Serverless": ("cloud", ["serverless"]),
    "Cloudflare": ("cloud", ["cloudflare", "workers"]),

    # ---------- infrastructure ----------
    "Kubernetes": ("infra", ["kubernetes", "k8s", "eks", "gke", "aks"]),
    "Docker": ("infra", ["docker", "containerization", "containers"]),
    "Terraform": ("infra", ["terraform", "opentofu"]),
    "CI/CD": ("infra", [r"ci/cd", "continuous integration", "continuous delivery",
                        "continuous deployment"]),
    "GitHub Actions": ("infra", ["github actions"]),
    "Jenkins": ("infra", ["jenkins"]),
    "Ansible": ("infra", ["ansible", "puppet", "chef"]),
    "Linux": ("infra", ["linux", "unix"]),
    "Git": ("infra", [r"\bgit\b", "version control"]),
    "Nginx": ("infra", ["nginx", "envoy", "haproxy"]),
    "Helm": ("infra", ["helm"]),
    "Service Mesh": ("infra", ["service mesh", "istio", "linkerd"]),
    "Infrastructure as Code": ("infra", ["infrastructure as code", "iac",
                                         "pulumi", "cloudformation", "cdk"]),
    "Observability": ("infra", ["observability", "opentelemetry", "otel",
                                "distributed tracing"]),
    "Monitoring": ("infra", ["monitoring", "prometheus", "grafana", "datadog",
                             "new relic", "splunk"]),
    "SRE": ("infra", ["site reliability", r"\bsre\b", "slo", "sli",
                      "error budget", "incident response", "on-call", "oncall"]),
    "Load Balancing": ("infra", ["load balancing", "load balancer"]),
    "Networking": ("infra", ["tcp/ip", "networking", "dns", "http/2"]),

    # ---------- data ----------
    "PostgreSQL": ("data", ["postgresql", "postgres"]),
    "MySQL": ("data", ["mysql", "mariadb"]),
    "MongoDB": ("data", ["mongodb", "mongo"]),
    "Redis": ("data", ["redis", "memcached", "valkey"]),
    "Elasticsearch": ("data", ["elasticsearch", "opensearch", "elastic"]),
    "Kafka": ("data", ["kafka", "pulsar"]),
    "Spark": ("data", ["apache spark", "pyspark", "spark"]),
    "Airflow": ("data", ["airflow", "dagster", "prefect"]),
    "dbt": ("data", [r"\bdbt\b"]),
    "Snowflake": ("data", ["snowflake"]),
    "BigQuery": ("data", ["bigquery"]),
    "Databricks": ("data", ["databricks"]),
    "ClickHouse": ("data", ["clickhouse", "duckdb"]),
    "Data Pipelines": ("data", ["data pipeline", "etl", "elt", "data warehouse",
                                "data lake", "lakehouse"]),
    "Streaming": ("data", ["stream processing", "streaming data", "flink",
                           "real-time data", "kinesis"]),
    "Cassandra": ("data", ["cassandra", "scylladb"]),
    # Vector databases are defined in the AI section - they belong with
    # retrieval rather than with general storage.

    # ---------- AI and machine learning ----------
    #
    # This section is deliberately detailed. "Machine learning" as one bucket
    # made an applied-AI job at an agent startup look identical to a computer
    # vision job from 2019, and it is precisely the newer vocabulary - agentic
    # systems, harnesses, evals, guardrails - that is moving fastest and is
    # most worth knowing about early.
    "Machine Learning": ("ai", ["machine learning", r"\bml\b"]),
    "Deep Learning": ("ai", ["deep learning", "neural network", "transformer"]),
    "PyTorch": ("ai", ["pytorch", "torch"]),
    "TensorFlow": ("ai", ["tensorflow", "keras", "jax"]),
    "scikit-learn": ("ai", ["scikit-learn", "sklearn", "pandas", "numpy"]),
    "LLMs": ("ai", ["large language model", r"\bllm\b", r"\bllms\b", "gpt",
                    "claude", "foundation model", "generative ai", "genai",
                    "frontier model"]),

    # --- agent engineering ---
    "Agentic Systems": ("ai", ["agentic", "ai agent", "autonomous agent",
                               "agent framework", "agent system", "agent loop",
                               "coding agent", "agent infrastructure"]),
    "Multi-Agent Orchestration": ("ai", ["multi-agent", "multi agent",
                                         "agent orchestration",
                                         "orchestrating agents",
                                         "agent handoff", "sub-agent",
                                         "subagent", "agent swarm"]),
    # "Harness" on its own also means a test harness, so the pattern requires
    # the AI sense explicitly.
    "Agent Harness": ("ai", [r"(?:agent|eval|evaluation|model|llm|inference|"
                             r"training|meta)[\s-]?harness(?:es)?\b",
                             r"harness engineering", r"meta[\s-]?harness",
                             r"agent scaffold\w*", r"scaffolding for agents"]),
    "Tool Calling": ("ai", ["tool calling", "tool-calling", "tool use",
                            "function calling", "tool invocation",
                            "structured output"]),
    "Agent Tracing": ("ai", ["agent tracing", "llm tracing", "llm observability",
                             "langsmith", "langfuse", "braintrust",
                             "trace agent", "agent telemetry",
                             "span", "opentelemetry for llm"]),
    "Agent Memory": ("ai", ["agent memory", "long-term memory", "memory layer",
                            "episodic memory", "conversation memory"]),
    "Context Engineering": ("ai", ["context engineering", "context window",
                                   "long context", "context management",
                                   "context compaction"]),
    "MCP": ("ai", [r"\bmcp\b", "model context protocol"]),

    # --- evaluation and safety ---
    "Evals": ("ai", [r"\bevals?\b", "eval harness", "eval suite", "eval set",
                     "model evaluation", "llm evaluation", "agent evaluation",
                     "offline eval", "llm-as-a-judge", "llm as judge",
                     "benchmarking models", "golden dataset", "regression suite"]),
    "Guardrails": ("ai", ["guardrail", "safety filter", "content filter",
                          "content moderation model", "safety classifier",
                          "model armor", "model armour", "llm firewall",
                          "refusal", "policy engine for"]),
    "AI Safety": ("ai", [r"ai safety", r"ai alignment", r"model alignment",
                         r"alignment research", r"responsible ai",
                         r"ai governance", r"model risk", r"bias mitigation",
                         r"interpretability"]),
    "AI Red Teaming": ("ai", ["red team", "red-team", "adversarial prompt",
                              "prompt injection", "jailbreak",
                              "adversarial testing", "abuse testing"]),

    # --- retrieval ---
    "RAG": ("ai", [r"\brag\b", "retrieval augmented", "retrieval-augmented",
                   "grounding", "citation generation"]),
    "Embeddings": ("ai", ["embedding", "embeddings", "vector representation",
                          "semantic search", "similarity search", "reranking",
                          "re-ranking", "hybrid search"]),
    "Vector Database": ("ai", ["vector database", "vector db", "vector store",
                               "pinecone", "weaviate", "milvus", "qdrant",
                               "pgvector", "chroma", "faiss", "lancedb",
                               "embeddings database", "vector index"]),

    # --- training and serving ---
    "Prompt Engineering": ("ai", ["prompt engineering", "prompting",
                                  "prompt design", "prompt template",
                                  "prompt optimization", "few-shot"]),
    "Fine-tuning": ("ai", ["fine-tuning", "fine tuning", "finetuning", "lora",
                           "qlora", "peft", "rlhf", "post-training", "dpo",
                           "reward model", "instruction tuning",
                           "supervised fine"]),
    "Model Serving": ("ai", ["model serving", "inference server", "vllm",
                             "triton", "model deployment", "tensorrt",
                             "sglang", "text generation inference"]),
    "Inference Optimization": ("ai", ["inference optimization", "inference latency",
                                      "inference cost", "quantization",
                                      "quantisation", "distillation",
                                      "speculative decoding", "continuous batching",
                                      "dynamic batching", "flash attention",
                                      "throughput optimization"]),
    "KV Caching": ("ai", [r"kv[\s-]?cach\w+", "key-value cache",
                          "prompt cach", "prefix cach", "attention cache"]),
    "Distributed Training": ("ai", ["distributed training", "model parallel",
                                    "data parallel", "fsdp", "deepspeed",
                                    "megatron", "training cluster",
                                    "multi-node training"]),
    "GPU Programming": ("ai", [r"\bcuda\b", r"\bgpu\b", r"\bgpus\b", "kernel fusion",
                               "triton kernel", "rocm", "tpu", "accelerator"]),
    "Synthetic Data": ("ai", ["synthetic data", "data generation pipeline",
                              "data flywheel"]),
    "LangChain": ("ai", ["langchain", "llamaindex", "langgraph", "llama-index",
                         "crewai", "autogen", "pydantic ai", "dspy",
                         "agents sdk", "openai sdk", "anthropic sdk"]),
    "MLOps": ("ai", ["mlops", "ml platform", "feature store", "mlflow",
                     "model registry", "weights & biases", "wandb",
                     "model versioning", "experiment tracking"]),
    "AI Assistants": ("ai", ["copilot", "ai assistant", "chatbot",
                             "conversational ai", "voice agent"]),

    # --- classic ML ---
    "Computer Vision": ("ai", ["computer vision", "image recognition",
                               "object detection", "opencv", "segmentation"]),
    "NLP": ("ai", ["natural language processing", r"\bnlp\b"]),
    "Recommendation Systems": ("ai", ["recommendation system", "recommender",
                                      "ranking system", "personalization"]),

    # ---------- system design ----------
    #
    # The things an interviewer actually probes in a design round, and that
    # postings ask for by name. These were previously invisible: "caching"
    # appears in 142 postings across 59 companies and was not tracked at all,
    # while Redis was - so the tool counted the product but missed the idea.
    "Caching": ("design", [r"\bcach\w+", "cache invalidation", "cache layer",
                           "write-through", "read-through", "cdn"]),
    "Message Queues": ("design", ["message queue", "pub/sub", "pubsub",
                                  "event-driven", "event driven", "event bus",
                                  "message broker", "rabbitmq", "sqs",
                                  "event sourcing", "asynchronous processing"]),
    "API Design": ("design", ["api design", "schema design", "api versioning",
                              "contract-first", "idempoten", "pagination",
                              "backwards compatib"]),
    "Scalability": ("design", ["horizontal scaling", "horizontally scalable",
                               "auto-scaling", "autoscaling", "capacity planning",
                               "scale to millions", "web scale", "sharding",
                               "shard", "partitioning"]),
    "High Availability": ("design", ["high availability", "disaster recovery",
                                     "failover", "redundancy", "replication",
                                     "multi-region", "zero downtime",
                                     "graceful degradation"]),
    "Rate Limiting": ("design", ["rate limiting", "rate limit", "throttling",
                                 "backpressure", "back-pressure",
                                 "circuit breaker", "exponential backoff"]),
    "Consistency": ("design", ["eventual consistency", "strong consistency",
                               "cap theorem", "acid", "transactional guarantee",
                               "consensus", "raft", "paxos"]),
    "Feature Flags": ("design", ["feature flag", "feature toggle",
                                 "canary release", "canary deploy",
                                 "blue-green", "progressive rollout",
                                 "a/b test"]),

    # ---------- security ----------
    "Security": ("security", ["application security", "appsec", "security engineering",
                              "threat model", "vulnerability"]),
    "Cryptography": ("security", ["cryptography", "encryption", "tls", "pki"]),
    "IAM": ("security", [r"\biam\b", "identity and access", "oauth", "saml",
                         "openid", "authentication", "authorization", "rbac"]),
    # Named standards only. A bare "compliance" appears in the legal footer of
    # almost every posting and would drown out everything else.
    "Compliance": ("security", ["soc 2", "soc2", "hipaa", "gdpr", "pci dss",
                                "fedramp", "iso 27001", "regulatory compliance",
                                "compliance requirements"]),
    "Zero Trust": ("security", ["zero trust", "zero-trust"]),
    "Penetration Testing": ("security", ["penetration testing", "pentest"]),
    "Secrets Management": ("security", ["secrets management", "secret management",
                                        "hashicorp vault", "key management",
                                        r"\bkms\b", "credential rotation",
                                        "certificate management"]),
    "Threat Modeling": ("security", ["threat model", "threat modeling",
                                     "threat modelling", "attack surface",
                                     "security review", "security design"]),
    "Data Privacy": ("security", [r"\bpii\b", "data privacy", "data governance",
                                  "data retention", "anonymi", "redaction",
                                  "ccpa", "privacy by design"]),
    "Supply Chain Security": ("security", ["supply chain security", r"\bsbom\b",
                                           "dependency scanning",
                                           "software composition analysis",
                                           "artifact signing", "sigstore"]),

    # ---------- practices ----------
    "Testing": ("practice", ["unit test", "unit testing", "integration test",
                             "test automation", "pytest", "jest", "test-driven",
                             "tdd", "end-to-end test"]),
    "Agile": ("practice", ["agile", "scrum", "kanban", "sprint"]),
    "Code Review": ("practice", ["code review", "peer review"]),
    "System Design": ("practice", ["system design", "distributed systems",
                                   "scalable systems", "architecture design",
                                   "high availability", "fault tolerance"]),
    "Data Structures": ("practice", ["data structures", "algorithms",
                                     "algorithmic", "computational complexity"]),
    "Performance": ("practice", ["performance optimization", "latency",
                                 "throughput", "profiling", "benchmarking"]),
    "Documentation": ("practice", ["technical documentation", "writing documentation"]),
    "Mentorship": ("practice", ["mentor", "mentoring", "mentorship"]),
    "Concurrency": ("practice", ["concurrency", "multithreading", "async",
                                 "parallel programming"]),
    "Debugging": ("practice", ["debugging", "troubleshooting", "root cause"]),
    "Open Source": ("practice", ["open source", "open-source", "oss contribution"]),

    # ---------- domains ----------
    "Payments": ("domain", ["payments", "billing", "fintech", "transactions"]),
    # "medical" is excluded on purpose: it matches the benefits line
    # ("medical, dental and vision") in nearly every posting.
    "Healthcare": ("domain", ["healthcare software", "clinical", "ehr", "emr",
                              "health system", "patient care", "life sciences",
                              "digital health"]),
    "E-commerce": ("domain", ["e-commerce", "ecommerce", "marketplace"]),
    "Gaming": ("domain", ["game development", "game engine", "unity", "unreal"]),
    "Robotics": ("domain", ["robotics", "autonomous vehicle", "ros"]),
    "Blockchain": ("domain", ["blockchain", "web3", "smart contract", "defi"]),
    "Developer Tools": ("domain", ["developer tools", "developer experience",
                                   "devex", "devtools", "internal tooling",
                                   "platform engineering"]),
    "Trading": ("domain", ["trading systems", "low latency trading",
                           "market data", "quantitative"]),
}

CATEGORY_LABELS = {
    "language": "Languages",
    "frontend": "Frontend",
    "backend": "Backend",
    "cloud": "Cloud",
    "infra": "Infrastructure",
    "data": "Data",
    "ai": "AI / ML",
    "security": "Security",
    "practice": "Practices",
    "design": "System Design",
    "domain": "Domains",
}


def category_of(skill: str) -> str:
    entry = SKILLS.get(skill)
    return entry[0] if entry else "other"


# ---------------------------------------------------------------------------
# Skills discovered by Claude and written to data/learned_skills.yml.
#
# They are merged in here so the rest of the system cannot tell the difference:
# a learned skill is matched, counted and charted exactly like a hand-written
# one. Claude proposes vocabulary; the dictionary still does the counting, so
# the numbers stay reproducible.
# ---------------------------------------------------------------------------

def _load_skill_file(path: Path) -> None:
    """Merge one YAML skill set into the dictionary."""
    if not path.exists():
        return
    try:
        import yaml

        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:  # noqa: BLE001 - a broken file must not break startup
        return
    for entry in data.get("skills") or []:
        name = (entry.get("name") or "").strip()
        aliases = [a for a in (entry.get("aliases") or []) if a]
        if name and aliases and name not in SKILLS:
            SKILLS[name] = (entry.get("category") or "practice", aliases)


def _load_profile_skills() -> None:
    """Apply the active profile: drop the built-in set if it is not wanted,
    then add whatever dictionaries the profile asks for.

    A product-management profile keeps the technical dictionary - those
    postings really do ask for SQL and APIs - and layers its own vocabulary on
    top. A profile for a non-technical role could switch the built-ins off.
    """
    from ..profiles import active

    profile = active()
    if not profile.include_builtin_skills:
        SKILLS.clear()
    base = Path(__file__).resolve().parent.parent.parent / "data" / "skills"
    for name in profile.skill_sets:
        _load_skill_file(base / f"{name}.yml")


def _load_learned() -> None:
    path = Path(__file__).resolve().parent.parent.parent / "data" / "learned_skills.yml"
    if not path.exists():
        return
    try:
        import yaml

        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:  # noqa: BLE001 - a broken learned file must not break startup
        return
    for entry in data.get("skills") or []:
        name = (entry.get("name") or "").strip()
        aliases = [a for a in (entry.get("aliases") or []) if a]
        if not name or not aliases or name in SKILLS:
            continue
        SKILLS[name] = (entry.get("category") or "practice", aliases)


_load_profile_skills()
_load_learned()
