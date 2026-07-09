from job_aggregator.cv.parser import parse_cv


SAMPLE_CV = """Nikhilesh Upreti
nikhilesh.upreti01@gmail.com | +91 98765 43210
linkedin.com/in/nikhilesh-upreti

Summary
Product manager with 5+ years of experience spanning engineering and product,
with a strong AI/LLM product background including RAG pipelines and LLM evals.

Experience
Trinity Lifesciences
Associate Product Manager
Jan 2023 - Present
- Owned roadmap for pharma analytics platform
- Led cross-functional stakeholder management across data science and eng

Zykrr
Product Manager
2021 - 2023
- Built RAG pipeline for customer feedback analysis using OpenAI API and LangChain
- Ran A/B testing on NPS survey flows

OneBanc
Software Engineer
2019 - 2021
- Built REST API services in Python with Postgres

Skills
Product Strategy, Roadmapping, Agile, Scrum, SQL, Python, Stakeholder Management

Projects
- Built an internal LLM evaluation harness using Claude API
- Shipped a Kubernetes-based deployment pipeline

Education
B.Tech Computer Science
"""


def test_parse_cv_extracts_contact_info():
    profile = parse_cv(SAMPLE_CV)
    assert profile.email == "nikhilesh.upreti01@gmail.com"
    assert "linkedin.com/in/nikhilesh-upreti" in profile.linkedin


def test_parse_cv_extracts_explicit_years():
    profile = parse_cv(SAMPLE_CV)
    assert profile.total_years_experience == 5.0


def test_parse_cv_extracts_roles_and_companies():
    profile = parse_cv(SAMPLE_CV)
    assert len(profile.roles) == 3
    assert "Trinity Lifesciences" in profile.companies
    assert "Zykrr" in profile.companies
    assert "OneBanc" in profile.companies


def test_parse_cv_extracts_skills_and_tools():
    profile = parse_cv(SAMPLE_CV)
    assert "product strategy" in profile.skills
    assert "stakeholder management" in profile.skills
    assert "python" in profile.tools
    assert "langchain" in profile.tools
    assert "claude api" in profile.tools


def test_parse_cv_keeps_raw_text():
    profile = parse_cv(SAMPLE_CV)
    assert "RAG pipeline" in profile.raw_text
