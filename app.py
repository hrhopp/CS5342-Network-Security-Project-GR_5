"""Streamlit UI for CS5342 local network-security tutor.

Run from the repository root (Ollama must be serving on 127.0.0.1):
    streamlit run app.py

.streamlit/config.toml binds this page to 127.0.0.1:8501 only.
Internet lookup is off by default; when on, only the question text leaves
the machine, and only through web.search.
"""
import streamlit as st

from web.search import learn_more, tutor
from quiz.generator import make_quiz, QuizError
from quiz.grader import GradingError, grade_quiz

st.set_page_config(page_title="CS5342 Security Tutor",
                   page_icon="🛡️", layout="centered")

st.markdown("""
<style>
    .stDeployButton, .stAppDeployButton {
        display: none !important;
}
</style>
""", unsafe_allow_html=True)


st.title("🛡️ Network Security Tutor")
st.caption("CS5342 · Local RAG tutor and quiz practice")

with st.sidebar:
    st.header("Privacy settings")
    allow_web = st.toggle(
        "Allow internet lookup when course material is insufficient", value=False
    )
    if allow_web:
        st.warning(
            "Internet lookup sends a sanitized question to an external search service. "
            "Do not enter private information."
        )
    else:
        st.success("Web lookup disabled")
    st.caption(
        "The local model and document database still require Ollama and an ingested knowledge base."
    )

tutor_tab, quiz_tab = st.tabs(
    ["💬 Ask the tutor", "📝 Practice quiz"]
)

with tutor_tab:
    if "history" not in st.session_state:
        st.session_state.history = []
    for entry in st.session_state.history:
        with st.chat_message("user"):
            st.write(entry["question"])
        with st.chat_message("assistant"):
            st.write(entry["text"])
            if entry["citations"]:
                with st.expander("Sources"):
                    for source in entry["citations"]:
                        st.write(f"• {source}")
            if entry["from_web"]:
                st.caption("Internet-assisted answer")
            if entry["blocked"]:
                st.warning("Response blocked by security checks")

    prompt = st.chat_input("Ask about TLS, firewalls, RSA, SYN floods...")
    if prompt:
        if len(prompt) > 500:
            st.error("Please limit questions to 500 characters.")
        else:
            with st.spinner("Searching course documents and preparing answer..."):
                try:
                    result = tutor(prompt, allow_web=allow_web)
                except Exception as exc:
                    st.error(f"Tutor unavailable: {exc}")
                else:
                    st.session_state.history.append({
                        "question": prompt,
                        "text": result.text,
                        "citations": getattr(result, "citations", []),
                        "from_web": getattr(result, "from_web", False),
                        "blocked": getattr(result, "blocked", False),
                    })
                    st.rerun()
    if st.button("Clear conversation"):
        st.session_state.history = []
        st.rerun()


with quiz_tab:
    st.subheader("Practice Quiz")
    st.caption("Generate questions from your network security course materials.")

    # --------------------------------------------------
    # Quiz configuration
    # --------------------------------------------------
    mode = st.radio(
        "Quiz mode",
        ["Topic", "Random"],
        horizontal=True,
    )

    topic = st.text_input(
        "Topic",
        placeholder="e.g., TLS, encryption, authentication",
        disabled=(mode == "Random"),
    )

    col1, col2, col3 = st.columns(3)

    with col1:
        mcq_count = st.number_input(
            "Multiple choice", min_value=0, max_value=20, value=3
        )

    with col2:
        tf_count = st.number_input(
            "True / False", min_value=0, max_value=20, value=2
        )

    with col3:
        open_count = st.number_input(
            "Open-ended", min_value=0, max_value=20, value=1
        )

    # --------------------------------------------------
    # Generate quiz
    # --------------------------------------------------
    if st.button("Generate Quiz", type="primary"):
        if mode == "Topic" and not topic.strip():
            st.warning("Please enter a topic.")
        elif mcq_count + tf_count + open_count == 0:
            st.warning("Select at least one question.")
        else:
            try:
                with st.spinner("Generating your quiz..."):
                    quiz = make_quiz(
                        topic=topic.strip() if mode == "Topic" else None,
                        counts={
                            "mcq": int(mcq_count),
                            "true_false": int(tf_count),
                            "open_ended": int(open_count),
                        },
                    )

                # Keep the original generated quiz data
                # on the server for grading.
                st.session_state["quiz_data"] = quiz.to_dict()

                # Increment version to reset answer widgets.
                st.session_state["quiz_version"] = (
                    st.session_state.get("quiz_version", 0) + 1
                )

                # Clear results from previous quiz.
                st.session_state.pop("quiz_grade", None)
                st.session_state.pop("quiz_links", None)

                st.rerun()

            except QuizError as exc:
                st.error(f"Quiz generation failed: {exc}")

    # --------------------------------------------------
    # Display generated quiz
    # --------------------------------------------------
    quiz_data = st.session_state.get("quiz_data")

    if quiz_data:
        questions = quiz_data["questions"]
        version = st.session_state.get("quiz_version", 0)

        st.divider()
        st.subheader("Your Quiz")

        with st.form(key=f"quiz_form_{version}"):

            for i, q in enumerate(questions):
                st.markdown(f"**Question {i + 1}**")
                st.write(q.get("text", q.get("question", "")))

                key = f"answer_{version}_{i}"

                if q["type"] == "mcq":
                    st.radio(
                        "Choose your answer",
                        options=q["options"],
                        index=None,
                        key=key,
                    )

                elif q["type"] == "true_false":
                    st.radio(
                        "Choose your answer",
                        options=["True", "False"],
                        index=None,
                        key=key,
                    )

                elif q["type"] == "open_ended":
                    st.text_area(
                        "Your answer",
                        placeholder="Enter your explanation...",
                        max_chars=4000,
                        key=key,
                    )

                st.divider()

            submitted = st.form_submit_button(
                "Grade Quiz",
                type="primary",
            )

        # --------------------------------------------------
        # Grade all questions using teammate's grader
        # --------------------------------------------------
        if submitted:
            answers = [
                st.session_state.get(f"answer_{version}_{i}")
                for i in range(len(questions))
            ]

            try:
                with st.spinner("Grading your quiz..."):
                    result = grade_quiz(
                        quiz_data,
                        answers,
                    )

                st.session_state["quiz_grade"] = result.to_dict()

                # Internet citations for feedback (opt-in). Fetched once here,
                # not on every rerun. Only the question text is sent.
                links = []
                if allow_web:
                    with st.spinner("Looking up internet references..."):
                        for q in questions:
                            found = learn_more(
                                q.get("text", ""), topic=quiz_data.get("topic"))
                            links.append([r.full_citation for r in found])
                st.session_state["quiz_links"] = links

            except GradingError as exc:
                st.session_state.pop("quiz_grade", None)
                st.error(f"Grading failed: {exc}")

            except Exception as exc:
                st.session_state.pop("quiz_grade", None)
                st.error(f"Unable to complete grading: {exc}")

        # --------------------------------------------------
        # Display grading results
        # --------------------------------------------------
        grade_data = st.session_state.get("quiz_grade")

        if grade_data:
            st.divider()
            st.subheader("Quiz Results")

            percentage = grade_data["percentage"]
            pending = grade_data["pending_count"]

            if percentage is not None:
                st.metric(
                    "Final Score",
                    f"{percentage:.1f}%",
                )
            else:
                st.warning(
                    f"{pending} question(s) require review. "
                    "A final percentage is not available yet."
                )

            st.write(
                f"**Points earned:** "
                f"{grade_data['earned_points']} / "
                f"{grade_data['possible_points']}"
            )

            # Individual question feedback
            for i, result in enumerate(grade_data["results"]):
                with st.expander(
                    f"Question {i + 1} — "
                    f"{result['status'].replace('_', ' ').title()}",
                    expanded=True,
                ):
                    st.write("**Question:**")
                    st.write(result["question"])

                    st.write("**Your answer:**")
                    st.write(
                        result["submitted_answer"]
                        or "No answer submitted"
                    )

                    if result["score"] is None:
                        st.warning(
                            "This answer requires instructor review."
                        )
                    else:
                        st.write(
                            f"**Score:** {result['score']:.2f} / 1"
                        )

                    if result.get("expected_answer"):
                        st.write("**Correct answer:**")
                        st.write(result["expected_answer"])

                    st.write("**Feedback:**")
                    st.write(result["feedback"])

                    if result.get("citation"):
                        st.caption(
                            f"Course source: {result['citation']}"
                        )

                    links = st.session_state.get("quiz_links") or []
                    if i < len(links) and links[i]:
                        st.write("**Learn more (internet):**")
                        for link in links[i]:
                            st.caption(link)
                    elif not allow_web:
                        st.caption(
                            "Turn on internet lookup in the sidebar before "
                            "grading to get internet references."
                        )

