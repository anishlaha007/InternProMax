"""Skills taxonomy + extraction from free text.

Each entry: canonical name -> (category, [aliases]). Aliases are matched case-insensitively
with tech-aware word boundaries unless listed in CASE_SENSITIVE / LIST_CONTEXT_ONLY.
"""

from __future__ import annotations

import re
from functools import lru_cache

SKILLS: dict[str, tuple[str, list[str]]] = {
    # ---- languages
    "Python": ("Languages", ["python", "python3"]),
    "Java": ("Languages", ["java"]),
    "C++": ("Languages", ["c++", "cpp"]),
    "C": ("Languages", []),
    "C#": ("Languages", ["c#", "csharp"]),
    "Go": ("Languages", ["golang"]),
    "Rust": ("Languages", ["rust"]),
    "JavaScript": ("Languages", ["javascript", "ecmascript", "es6"]),
    "TypeScript": ("Languages", ["typescript"]),
    "Kotlin": ("Languages", ["kotlin"]),
    "Swift": ("Languages", ["swift"]),
    "Objective-C": ("Languages", ["objective-c", "objective c"]),
    "Scala": ("Languages", ["scala"]),
    "Ruby": ("Languages", ["ruby"]),
    "PHP": ("Languages", ["php"]),
    "R": ("Languages", []),
    "MATLAB": ("Languages", ["matlab"]),
    "Julia": ("Languages", ["julia"]),
    "SQL": ("Languages", ["sql"]),
    "Bash": ("Languages", ["bash", "shell scripting", "shell script", "zsh"]),
    "Perl": ("Languages", ["perl"]),
    "Haskell": ("Languages", ["haskell"]),
    "OCaml": ("Languages", ["ocaml"]),
    "Elixir": ("Languages", ["elixir"]),
    "Dart": ("Languages", ["dart"]),
    "Lua": ("Languages", ["lua"]),
    "Assembly": ("Languages", ["assembly", "x86 assembly", "arm assembly"]),
    "Verilog": ("Languages", ["verilog", "systemverilog"]),
    "VHDL": ("Languages", ["vhdl"]),
    "HTML": ("Languages", ["html", "html5"]),
    "CSS": ("Languages", ["css", "css3", "sass", "scss"]),
    "Solidity": ("Languages", ["solidity"]),
    "CUDA": ("Languages", ["cuda"]),
    "LabVIEW": ("Languages", ["labview"]),
    # ---- web / backend frameworks
    "React": ("Frameworks", ["react", "react.js", "reactjs"]),
    "React Native": ("Frameworks", ["react native"]),
    "Next.js": ("Frameworks", ["next.js", "nextjs"]),
    "Vue": ("Frameworks", ["vue", "vue.js", "vuejs"]),
    "Angular": ("Frameworks", ["angular", "angularjs"]),
    "Svelte": ("Frameworks", ["svelte", "sveltekit"]),
    "Node.js": ("Frameworks", ["node.js", "nodejs"]),
    "Express": ("Frameworks", ["express.js", "expressjs"]),
    "Django": ("Frameworks", ["django"]),
    "Flask": ("Frameworks", ["flask"]),
    "FastAPI": ("Frameworks", ["fastapi"]),
    "Spring": ("Frameworks", ["spring boot", "spring framework", "springboot"]),
    "Ruby on Rails": ("Frameworks", ["rails", "ruby on rails"]),
    ".NET": ("Frameworks", [".net", "asp.net", "dotnet", ".net core"]),
    "GraphQL": ("Frameworks", ["graphql"]),
    "REST APIs": ("Concepts", ["restful", "rest api", "rest apis", "restful apis"]),
    "gRPC": ("Frameworks", ["grpc", "protobuf", "protocol buffers"]),
    "Tailwind CSS": ("Frameworks", ["tailwind", "tailwindcss"]),
    "Redux": ("Frameworks", ["redux"]),
    "Flutter": ("Frameworks", ["flutter"]),
    "SwiftUI": ("Frameworks", ["swiftui"]),
    "Jetpack Compose": ("Frameworks", ["jetpack compose"]),
    "Unity": ("Frameworks", ["unity3d", "unity engine"]),
    "Unreal Engine": ("Frameworks", ["unreal engine", "unreal", "ue5", "ue4"]),
    "Qt": ("Frameworks", ["qt"]),
    "ROS": ("Frameworks", ["ros", "ros2", "robot operating system"]),
    # ---- data / ML
    "Machine Learning": ("ML/Data", ["machine learning", "ml"]),
    "Deep Learning": ("ML/Data", ["deep learning", "neural networks", "neural network"]),
    "NLP": ("ML/Data", ["nlp", "natural language processing"]),
    "Computer Vision": ("ML/Data", ["computer vision", "image processing"]),
    "LLMs": ("ML/Data", ["llm", "llms", "large language models", "large language model", "generative ai", "genai"]),
    "Reinforcement Learning": ("ML/Data", ["reinforcement learning"]),
    "PyTorch": ("ML/Data", ["pytorch", "torch"]),
    "TensorFlow": ("ML/Data", ["tensorflow", "keras"]),
    "JAX": ("ML/Data", ["jax"]),
    "scikit-learn": ("ML/Data", ["scikit-learn", "sklearn", "scikit learn"]),
    "Pandas": ("ML/Data", ["pandas"]),
    "NumPy": ("ML/Data", ["numpy"]),
    "SciPy": ("ML/Data", ["scipy"]),
    "Hugging Face": ("ML/Data", ["hugging face", "huggingface", "transformers library"]),
    "LangChain": ("ML/Data", ["langchain"]),
    "OpenCV": ("ML/Data", ["opencv"]),
    "Spark": ("ML/Data", ["pyspark", "apache spark"]),
    "Hadoop": ("ML/Data", ["hadoop"]),
    "Kafka": ("ML/Data", ["kafka"]),
    "Airflow": ("ML/Data", ["airflow"]),
    "dbt": ("ML/Data", []),
    "Tableau": ("ML/Data", ["tableau"]),
    "Power BI": ("ML/Data", ["power bi", "powerbi"]),
    "Excel": ("ML/Data", ["microsoft excel", "ms excel", "vba"]),
    "Statistics": ("ML/Data", ["statistics", "statistical", "statistical analysis", "probability"]),
    "Data Analysis": ("ML/Data", ["data analysis", "data analytics", "analytics"]),
    "Data Visualization": ("ML/Data", ["data visualization", "matplotlib", "seaborn", "plotly", "d3.js"]),
    "ETL": ("ML/Data", ["etl", "data pipelines", "data pipeline", "elt"]),
    "A/B Testing": ("ML/Data", ["a/b testing", "a/b tests", "experimentation"]),
    "MLOps": ("ML/Data", ["mlops", "mlflow", "kubeflow"]),
    # ---- databases
    "PostgreSQL": ("Databases", ["postgresql", "postgres"]),
    "MySQL": ("Databases", ["mysql"]),
    "SQLite": ("Databases", ["sqlite"]),
    "MongoDB": ("Databases", ["mongodb", "mongo"]),
    "Redis": ("Databases", ["redis"]),
    "Cassandra": ("Databases", ["cassandra"]),
    "DynamoDB": ("Databases", ["dynamodb"]),
    "Elasticsearch": ("Databases", ["elasticsearch", "opensearch"]),
    "Snowflake": ("Databases", ["snowflake"]),
    "BigQuery": ("Databases", ["bigquery"]),
    "NoSQL": ("Databases", ["nosql"]),
    "Vector Databases": ("Databases", ["vector database", "vector databases", "pinecone", "faiss", "pgvector"]),
    # ---- cloud / devops
    "AWS": ("Cloud/DevOps", ["aws", "amazon web services", "ec2", "s3", "lambda"]),
    "GCP": ("Cloud/DevOps", ["gcp", "google cloud", "google cloud platform"]),
    "Azure": ("Cloud/DevOps", ["azure", "microsoft azure"]),
    "Docker": ("Cloud/DevOps", ["docker", "containers", "containerization"]),
    "Kubernetes": ("Cloud/DevOps", ["kubernetes", "k8s", "helm"]),
    "Terraform": ("Cloud/DevOps", ["terraform", "infrastructure as code"]),
    "CI/CD": ("Cloud/DevOps", ["ci/cd", "continuous integration", "continuous delivery", "continuous deployment", "github actions", "jenkins", "gitlab ci"]),
    "Linux": ("Cloud/DevOps", ["linux", "unix"]),
    "Git": ("Tools", ["git", "github", "gitlab", "version control"]),
    "Microservices": ("Concepts", ["microservices", "microservice", "service-oriented architecture"]),
    "Distributed Systems": ("Concepts", ["distributed systems", "distributed system", "distributed computing", "consensus", "raft", "paxos", "replication", "replicated", "fault tolerance", "fault-tolerant"]),
    "Cloud Computing": ("Concepts", ["cloud computing", "cloud infrastructure", "cloud services"]),
    "Networking": ("Concepts", ["networking", "tcp/ip", "network protocols"]),
    "Operating Systems": ("Concepts", ["operating systems", "operating system", "kernel", "os internals"]),
    "Concurrency": ("Concepts", ["concurrency", "multithreading", "multi-threading", "parallel programming", "parallel computing"]),
    "Data Structures & Algorithms": ("Concepts", ["data structures", "algorithms", "data structures and algorithms"]),
    "Object-Oriented Programming": ("Concepts", ["object-oriented", "object oriented", "oop"]),
    "System Design": ("Concepts", ["system design", "systems design", "software architecture", "scalable systems"]),
    "Testing": ("Concepts", ["unit testing", "unit tests", "test automation", "automated testing", "pytest", "junit", "jest", "selenium", "cypress", "tdd"]),
    "Agile": ("Concepts", ["agile", "scrum", "kanban", "jira"]),
    "Security": ("Concepts", ["cybersecurity", "security", "cryptography", "penetration testing", "vulnerability", "infosec"]),
    "Compilers": ("Concepts", ["compilers", "compiler", "llvm"]),
    "Databases": ("Concepts", ["database design", "databases", "relational databases", "data modeling"]),
    "Mobile Development": ("Concepts", ["mobile development", "ios development", "android development", "mobile apps", "mobile applications"]),
    "iOS": ("Concepts", ["ios", "xcode"]),
    "Android": ("Concepts", ["android"]),
    "Web Development": ("Concepts", ["web development", "web applications", "web apps", "frontend development", "full-stack", "full stack"]),
    "Frontend": ("Concepts", ["frontend", "front-end", "front end", "ui development"]),
    "Backend": ("Concepts", ["backend", "back-end", "back end", "server-side"]),
    "APIs": ("Concepts", ["apis", "api design", "api development"]),
    "Performance Optimization": ("Concepts", ["performance optimization", "low latency", "low-latency", "high performance", "high-performance", "profiling"]),
    # ---- hardware / embedded
    "Embedded Systems": ("Hardware", ["embedded systems", "embedded software", "embedded", "firmware", "microcontrollers", "microcontroller", "rtos"]),
    "FPGA": ("Hardware", ["fpga", "fpgas"]),
    "ASIC": ("Hardware", ["asic", "asics", "rtl", "rtl design"]),
    "PCB Design": ("Hardware", ["pcb", "pcb design", "altium", "kicad", "eagle"]),
    "Circuit Design": ("Hardware", ["circuit design", "analog design", "digital design", "circuits", "spice", "ltspice"]),
    "Signal Processing": ("Hardware", ["signal processing", "dsp", "digital signal processing"]),
    "Arduino": ("Hardware", ["arduino", "raspberry pi"]),
    "CAD": ("Hardware", ["cad", "solidworks", "autocad", "fusion 360", "creo", "catia", "nx cad"]),
    "Robotics": ("Hardware", ["robotics", "robot", "robots", "motion planning", "slam"]),
    "Controls": ("Hardware", ["control systems", "controls", "pid", "simulink"]),
    "Computer Architecture": ("Hardware", ["computer architecture", "cpu design", "gpu architecture"]),
    # ---- quant / finance
    "Quantitative Analysis": ("Quant", ["quantitative analysis", "quantitative research", "quantitative", "quant"]),
    "Trading": ("Quant", ["trading", "market making", "derivatives", "options pricing"]),
    "Financial Modeling": ("Quant", ["financial modeling", "valuation", "dcf"]),
    "Stochastic Calculus": ("Quant", ["stochastic calculus", "stochastic processes"]),
    "Linear Algebra": ("Quant", ["linear algebra"]),
    "Optimization": ("Quant", ["optimization", "convex optimization", "operations research"]),
    # ---- product / design
    "Product Management": ("Product", ["product management", "product strategy", "roadmap", "roadmaps", "prd", "prds"]),
    "User Research": ("Product", ["user research", "user interviews", "usability testing", "ux research"]),
    "Figma": ("Product", ["figma", "sketch", "wireframes", "wireframing", "prototyping"]),
    "UI/UX Design": ("Product", ["ui/ux", "ux design", "ui design", "user experience", "product design"]),
    # ---- soft skills (kept small; used for resume emphasis)
    "Communication": ("Soft skills", ["communication skills", "written communication", "verbal communication"]),
    "Leadership": ("Soft skills", ["leadership", "led a team", "mentoring"]),
    "Teamwork": ("Soft skills", ["collaboration", "collaborative", "teamwork", "cross-functional"]),
    "Problem Solving": ("Soft skills", ["problem solving", "problem-solving", "analytical skills"]),
}

# Aliases matched case-sensitively (short or ambiguous words).
CASE_SENSITIVE = {"Spark": ["Spark"], "Excel": ["Excel"], "Unity": ["Unity"], "dbt": ["dbt"]}
# Single letters / common words only matched in list-like contexts ("Python, Go, and R").
LIST_CONTEXT_ONLY = {"Go": ["Go"], "R": ["R"], "C": ["C"]}

_B_LEFT = r"(?<![\w+#.\-])"
_B_RIGHT = r"(?![\w+#]|\.\w)"


@lru_cache(maxsize=1)
def _compiled() -> list[tuple[str, re.Pattern]]:
    out: list[tuple[str, re.Pattern]] = []
    for name, (_cat, aliases) in SKILLS.items():
        alts = {a.lower() for a in aliases}
        if name not in LIST_CONTEXT_ONLY and name not in CASE_SENSITIVE:
            alts.add(name.lower())
        if alts:
            body = "|".join(re.escape(a) for a in sorted(alts, key=len, reverse=True))
            out.append((name, re.compile(_B_LEFT + "(?:" + body + ")" + _B_RIGHT, re.I)))
        for word in CASE_SENSITIVE.get(name, []):
            out.append((name, re.compile(r"\b" + re.escape(word) + r"\b(?!\s+(?:in|at)\b)")))
        for word in LIST_CONTEXT_ONLY.get(name, []):
            w = re.escape(word)
            out.append((name, re.compile(
                r"(?:(?<=[,(/:;])\s*" + w + r"(?![\w+#])|(?<![\w.+#-])" + w + r"(?=\s*[,)/;])"
                r"|(?<=\band )" + w + r"\b(?![+#&])|(?<=\bor )" + w + r"\b(?![+#&]))"
            )))
    return out


def extract(text: str) -> list[str]:
    """Canonical skills mentioned in text, ordered by first appearance."""
    if not text:
        return []
    hits: dict[str, int] = {}
    for name, pat in _compiled():
        m = pat.search(text)
        if m and (name not in hits or m.start() < hits[name]):
            hits[name] = m.start()
    return [k for k, _ in sorted(hits.items(), key=lambda kv: kv[1])]


def canonical(skill: str) -> str:
    """Map a user-typed skill to the canonical name when we know it."""
    s = skill.strip()
    low = s.lower()
    for name, (_cat, aliases) in SKILLS.items():
        if low == name.lower() or low in (a.lower() for a in aliases):
            return name
    return s


def category_of(skill: str) -> str:
    entry = SKILLS.get(canonical(skill))
    return entry[0] if entry else "Other"


def mentions(text: str, skill: str) -> bool:
    """Does text mention this skill (canonical or free-form)?"""
    canon = canonical(skill)
    if canon in SKILLS:
        return canon in extract(text)
    return re.search(_B_LEFT + re.escape(skill.lower()) + _B_RIGHT, text.lower()) is not None


# Role families used to match job titles against interests.
ROLE_FAMILIES: dict[str, list[str]] = {
    "Software Engineering": ["software engineer", "software engineering", "software developer", "software development", "swe", "sde", "developer", "programmer"],
    "Backend": ["backend", "back-end", "back end", "server", "platform", "infrastructure", "distributed", "api"],
    "Frontend": ["frontend", "front-end", "front end", "ui engineer", "web", "react"],
    "Full Stack": ["full stack", "full-stack", "fullstack", "web"],
    "Mobile": ["mobile", "ios", "android"],
    "Machine Learning / AI": ["machine learning", "ml", "ai", "artificial intelligence", "deep learning", "llm", "nlp", "computer vision", "genai", "applied scientist", "perception"],
    "Data Science": ["data science", "data scientist", "analytics", "data analyst", "business intelligence", "statistic"],
    "Data Engineering": ["data engineer", "data engineering", "data platform", "etl"],
    "Security": ["security", "cyber", "cybersecurity", "infosec", "offensive", "threat"],
    "Cloud / DevOps / SRE": ["devops", "sre", "site reliability", "cloud", "infrastructure", "platform engineer", "reliability"],
    "Embedded / Firmware": ["embedded", "firmware", "microcontroller", "rtos"],
    "Hardware / Electrical": ["hardware", "electrical", "fpga", "asic", "silicon", "chip", "circuit", "rf ", "pcb", "power electronics"],
    "Robotics / Autonomy": ["robotics", "robot", "autonomy", "autonomous", "controls", "perception", "slam"],
    "Quant / Trading": ["quant", "quantitative", "trading", "trader", "strategist"],
    "Research": ["research", "researcher", "scientist"],
    "Product Management": ["product manager", "product management", "apm", "product intern", "program manager"],
    "Design / UX": ["designer", "ux", "ui/ux", "product design"],
    "Game Development": ["game", "gameplay", "graphics", "rendering"],
    "Test / QA": ["test", "qa", "quality", "validation", "verification"],
}


@lru_cache(maxsize=256)
def _title_pattern(keyword: str) -> re.Pattern:
    kw = keyword.strip().lower()
    return re.compile(r"(?<![a-z0-9])" + re.escape(kw).replace(r"\ ", r"[\s\-/]+") + r"(?![a-z0-9])", re.I)


def title_has(title: str, keyword: str) -> bool:
    if not keyword or not keyword.strip():
        return False
    return _title_pattern(keyword).search(title) is not None
