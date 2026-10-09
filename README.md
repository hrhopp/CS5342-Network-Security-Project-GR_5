# CS5342-Network-Security-Project-GR_5
Our own personalized agent utilizing the capabilities of a Large Language Model (LLM) to engage with network security documents.

# Instructions
Your task is to build an Agent-Based Intelligent Tutor that (1) answers course questions with
citations and (2) generates and grades quizzes across multiple formats. It is mandatory to keep the
data on your local system since data privacy can be compromised when sending data over the
internet. In details, your bot should have two Agents.
• Q&A Tutor Agent (1st). Your agent should be able to understand user questions and
provide appropriate answers from the local database, then the citations should be added
(must be accomplished) including the web references if the response is from the internet.
• Quiz Agent (2nd). Your agent should be able to offer two types of questions: 1. randomly
generated questions and 2. specific topic questions and the answers should be pulled from
the network security database. The quiz must include multiple-choice questions, true/false
questions, and open-ended questions. Finally, the bot should be able to provide feedback
on the user's answers with citations including citations from the internet. We will also check
how close your agent’s response matches the correct answer, and then give your bot a grade
based on that.
• Train your bot using network security lecture slides, network security textbook, quizzes,
and the internet.
• (Bonus) we will award bonus points to teams that develop additional creative security
hardening beyond the requirements below, such as access control or session management
on your user interface, or encryption of the local vector database at rest.
