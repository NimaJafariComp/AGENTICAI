import streamlit as st


st.set_page_config(page_title="AgenticAI", page_icon=":package:", layout="wide")

st.title("AgenticAI")
st.caption("Milestone 1 scaffold")

st.write(
    "This placeholder UI confirms the local frontend boots while the refund "
    "agent, policy engine, and trace dashboard are still under construction."
)

st.info(
    "Next milestones will add customer chat, protected refund actions, "
    "deterministic policy decisions, and admin traces."
)
