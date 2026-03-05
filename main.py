from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
from groq import Groq
from dotenv import load_dotenv
from sqlalchemy import create_engine, Column, Integer, String, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from fpdf import FPDF
import os
import tempfile

load_dotenv()

# ─── BASE DE DATOS ───────────────────────────────────────────
# ✅ En local usa SQLite, en producción usa PostgreSQL de Supabase
DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "sqlite:///./propuestas.db"  # Fallback para desarrollo local
)

# ✅ Fix necesario: Render usa "postgres://" pero SQLAlchemy necesita "postgresql://"
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

# ✅ connect_args solo aplica para SQLite
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if "sqlite" in DATABASE_URL else {}
)

SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()

class Propuesta(Base):
    __tablename__ = "propuestas"
    id       = Column(Integer, primary_key=True, index=True)
    cliente  = Column(String(200))
    servicio = Column(String(200))
    texto    = Column(Text)

Base.metadata.create_all(bind=engine)  # ✅ Crea la tabla si no existe

# ─── FASTAPI ──────────────────────────────────────────────────
app = FastAPI()

# ✅ CORS actualizado para desarrollo local y producción en Vercel/Netlify
origins = [
    "http://localhost",
    "http://localhost:5500",
    "http://127.0.0.1:5500",
    "http://127.0.0.1",
    "https://tu-proyecto.vercel.app",    # ← Reemplaza con tu URL real de Vercel
    "https://tu-proyecto.netlify.app",   # ← Reemplaza con tu URL real de Netlify
    "*"  # ← Puedes quitar esto después de tener las URLs reales
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

client = Groq(api_key=os.environ.get("GROQ_API_KEY"))

# ─── MODELO ───────────────────────────────────────────────────
class ClienteServicio(BaseModel):
    cliente: str
    servicio: str

# ─── ENDPOINT: GENERAR PROPUESTA ─────────────────────────────
@app.post("/generar_parrafo/")
async def generar_parrafo(datos: ClienteServicio):

    system_prompt = """
    Eres un Copywriter Experto en Ventas B2B con 15 años de experiencia ayudando a freelancers 
    a cerrar contratos de alto valor. Tu escritura es persuasiva, profesional y orientada a resultados.
    
    Cuando recibas el nombre de un cliente y un tipo de servicio, debes generar una propuesta 
    comercial completa con esta estructura:
    
    1. SALUDO PERSONALIZADO — Dirígete al cliente por su nombre de forma cálida y profesional.
    
    2. ENTENDIMIENTO DEL PROBLEMA — Muestra que comprendes los desafíos típicos de alguien 
       que necesita ese servicio. Demuestra empatía y conocimiento del sector.
    
    3. SOLUCIÓN PROPUESTA — Describe cómo tu servicio resuelve exactamente ese problema. 
       Sé específico, usa lenguaje de beneficios (no solo características).
    
    4. TIEMPOS ESTIMADOS — Incluye un cronograma lógico y realista:
       - Semana 1: (fase inicial)
       - Semana 2-3: (desarrollo/ejecución)
       - Semana 4: (entrega y ajustes)
    
    5. LLAMADO A LA ACCIÓN — Cierra con urgencia suave y próximos pasos concretos.
    
    Tono: Profesional pero cercano. Evita tecnicismos innecesarios. Máximo 400 palabras.
    """

    user_prompt = f"""
    Genera una propuesta comercial para:
    - Nombre del cliente: {datos.cliente}
    - Servicio solicitado: {datos.servicio}
    """

    try:
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": user_prompt}
            ],
            max_tokens=600,
            temperature=0.7
        )
        texto = response.choices[0].message.content

        # ✅ Guardar en base de datos
        db = SessionLocal()
        nueva = Propuesta(cliente=datos.cliente, servicio=datos.servicio, texto=texto)
        db.add(nueva)
        db.commit()
        db.refresh(nueva)
        propuesta_id = nueva.id
        db.close()

        return {"propuesta": texto, "id": propuesta_id}

    except Exception as e:
        return {"error": f"Hubo un problema con la API de Groq: {str(e)}"}


# ─── ENDPOINT: HISTORIAL ──────────────────────────────────────
@app.get("/propuestas/")
async def listar_propuestas():
    db = SessionLocal()
    propuestas = db.query(Propuesta).all()
    db.close()
    return [{"id": p.id, "cliente": p.cliente, "servicio": p.servicio} for p in propuestas]


# ─── ENDPOINT: DESCARGAR PDF ──────────────────────────────────
@app.get("/descargar_pdf/{propuesta_id}")
async def descargar_pdf(propuesta_id: int):

    db = SessionLocal()
    propuesta = db.query(Propuesta).filter(Propuesta.id == propuesta_id).first()
    db.close()

    if not propuesta:
        raise HTTPException(status_code=404, detail="Propuesta no encontrada")

    # ✅ Generar PDF
    pdf = FPDF()
    pdf.add_page()
    pdf.set_margins(20, 20, 20)

    # Título
    pdf.set_font("Helvetica", "B", 20)
    pdf.set_text_color(15, 23, 42)
    pdf.cell(0, 12, "Propuesta Comercial", ln=True, align="C")
    pdf.ln(4)

    # Línea decorativa dorada
    pdf.set_draw_color(232, 201, 126)
    pdf.set_line_width(0.8)
    pdf.line(20, pdf.get_y(), 190, pdf.get_y())
    pdf.ln(8)

    # Cliente y Servicio
    pdf.set_font("Helvetica", "B", 11)
    pdf.set_text_color(100, 116, 139)
    pdf.cell(0, 7, f"Cliente:   {propuesta.cliente}", ln=True)
    pdf.cell(0, 7, f"Servicio:  {propuesta.servicio}", ln=True)
    pdf.ln(6)

    # Línea separadora
    pdf.set_draw_color(226, 232, 240)
    pdf.set_line_width(0.3)
    pdf.line(20, pdf.get_y(), 190, pdf.get_y())
    pdf.ln(8)

    # Texto de la propuesta
    pdf.set_font("Helvetica", "", 11)
    pdf.set_text_color(30, 41, 59)
    pdf.multi_cell(0, 7, propuesta.texto)
    pdf.ln(10)

    # Footer
    pdf.set_y(-20)
    pdf.set_font("Helvetica", "I", 9)
    pdf.set_text_color(148, 163, 184)
    pdf.cell(0, 10, "Generado con ProposalAI - Tu herramienta de propuestas para freelancers", align="C")

    # Guardar en archivo temporal
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
    pdf.output(tmp.name)

    return FileResponse(
        path=tmp.name,
        media_type="application/pdf",
        filename=f"propuesta_{propuesta.cliente.replace(' ', '_')}.pdf"
    )