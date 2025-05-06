import os
import base64
import gc
import tempfile
import uuid

from llama_index.core import Settings
from llama_index.llms.groq import Groq  # <-- Updated to use Groq
from llama_index.core import PromptTemplate
from llama_index.embeddings.huggingface import HuggingFaceEmbedding
from llama_index.core import VectorStoreIndex, SimpleDirectoryReader
import nest_asyncio


import streamlit as st

nest_asyncio.apply()


# Initialize session state
if "id" not in st.session_state:
    st.session_state.id = uuid.uuid4()
    st.session_state.file_cache = {}

session_id = st.session_state.id

@st.cache_resource
def load_llm():
    # Use the Groq model
    llm = Groq(model="deepseek-r1-distill-llama-70b", request_timeout=120.0)
    return llm

def reset_chat():
    st.session_state.messages = []
    st.session_state.context = None
    gc.collect()

def display_pdf(file):
    st.markdown("### PDF Preview")
    base64_pdf = base64.b64encode(file.read()).decode("utf-8")
    pdf_display = f"""<iframe src="data:application/pdf;base64,{base64_pdf}" width="400" height="100%" type="application/pdf"
                        style="height:100vh; width:100%">
                    </iframe>"""
    st.markdown(pdf_display, unsafe_allow_html=True)

with st.sidebar:
    st.header("Add your documents!")
    
    uploaded_file = st.file_uploader("Choose your `.pdf` file", type="pdf")

    if uploaded_file:
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                file_path = os.path.join(temp_dir, uploaded_file.name)
                
                with open(file_path, "wb") as f:
                    f.write(uploaded_file.getvalue())
                
                file_key = f"{session_id}-{uploaded_file.name}"
                st.write("Indexing your document...")

                if file_key not in st.session_state.get('file_cache', {}):

                    if os.path.exists(temp_dir):
                        loader = SimpleDirectoryReader(
                            input_dir=temp_dir,
                            required_exts=[".pdf"],
                            recursive=True
                        )
                    else:    
                        st.error('Could not find the file you uploaded, please check again...')
                        st.stop()
                    
                    docs = loader.load_data()

                    # Setup LLM & embedding model
                    llm = load_llm()
                    embed_model = HuggingFaceEmbedding(model_name="BAAI/bge-large-en-v1.5", trust_remote_code=True, use_transformers=True)

                    Settings.embed_model = embed_model
                    index = VectorStoreIndex.from_documents(docs, show_progress=True)

                    Settings.llm = llm
                    query_engine = index.as_query_engine(streaming=True)

                    # Custom prompt template
                    qa_prompt_tmpl_str = (
                        "Context information is below.\n"
                        "---------------------\n"
                        "{context_str}\n"
                        "---------------------\n"
                        "Given the context information above I want you to think step by step "
                        "to answer the query in a crisp manner, incase you don't know the answer say 'I don't know!'.\n"
                        "Query: {query_str}\n"
                        "Answer: "
                    )
                    qa_prompt_tmpl = PromptTemplate(qa_prompt_tmpl_str)

                    query_engine.update_prompts({
                        "response_synthesizer:text_qa_template": qa_prompt_tmpl
                    })

                    st.session_state.file_cache[file_key] = query_engine
                else:
                    query_engine = st.session_state.file_cache[file_key]

                # Inform the user that the file is processed and display the PDF uploaded
                st.success("Ready to Chat!")
                display_pdf(uploaded_file)

        except Exception as e:
            st.error(f"An error occurred: {e}")
            st.stop()     

# UI Layout
col1, col2 = st.columns([6, 1])
with col1:
    st.header("Chat with Docs using DeepSeek on Groq")
with col2:
    st.button("Clear ↺", on_click=reset_chat)

# Initialize chat history
if "messages" not in st.session_state:
    reset_chat()

# Display chat history
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# Accept user input
if prompt := st.chat_input("What's up?"):
    st.session_state.messages.append({"role": "user", "content": prompt})

    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        message_placeholder = st.empty()
        full_response = ""

        streaming_response = query_engine.query(prompt)

        for chunk in streaming_response.response_gen:
            full_response += chunk
            message_placeholder.markdown(full_response + "▌")

        message_placeholder.markdown(full_response)

    st.session_state.messages.append({"role": "assistant", "content": full_response})
