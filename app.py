import streamlit as st
import sqlite3
from datetime import datetime
import re
import cv2
import pandas as pd
from PIL import Image
import io
import numpy as np
import pytesseract

# Configura o caminho do Tesseract no Streamlit Cloud
pytesseract.pytesseract.tesseract_cmd = '/usr/bin/tesseract'

# Configuração inicial do Streamlit
st.set_page_config(page_title="Controle de Acesso Carbon", layout="wide", page_icon="🚗")

class VehicleAccessSystem:
    def __init__(self):
        self.conn = sqlite3.connect('carbon_access.db')
        self.create_database()

    def create_database(self):
        cursor = self.conn.cursor()
        
        # Tabela de colaboradores
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS colaboradores (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nome TEXT NOT NULL,
                cargo TEXT NOT NULL,
                tag_id TEXT UNIQUE,
                foto BLOB,
                ativo BOOLEAN DEFAULT 1
            )
        ''')
        
        # Tabela de veículos
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS veiculos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                placa TEXT UNIQUE NOT NULL,
                modelo TEXT,
                marca TEXT,
                cor TEXT,
                colaborador_id INTEGER,
                tipo_veiculo TEXT CHECK(tipo_veiculo IN ('Diretor', 'Gerente', 'Funcionario', 'Visitante')),
                FOREIGN KEY (colaborador_id) REFERENCES colaboradores(id)
            )
        ''')
        
        # Tabela de histórico de acessos
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS acessos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                veiculo_id INTEGER,
                data_hora TEXT NOT NULL,
                acesso_permitido BOOLEAN,
                observacoes TEXT,
                FOREIGN KEY (veiculo_id) REFERENCES veiculos(id)
            )
        ''')
        
        self.conn.commit()

    def validate_plate(self, plate):
        """Valida o formato da placa (Mercosul ou padrão antigo)"""
        pattern_mercosul = r'^[A-Z]{3}[0-9][A-Z0-9][0-9]{2}$'
        pattern_antigo = r'^[A-Z]{3}[0-9]{4}$'
        return bool(re.match(pattern_mercosul, plate.upper()) or re.match(pattern_antigo, plate.upper()))

    def recognize_plate(self, image):
        """Reconhece a placa do veículo usando OCR"""
        try:
            # Carrega a imagem
            if isinstance(image, str):
                img = cv2.imread(image)
            else:
                img = cv2.imdecode(np.frombuffer(image.read(), np.uint8), cv2.IMREAD_COLOR)
            
            # Pré-processamento avançado da imagem
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            gray = cv2.equalizeHist(gray)  # Melhora contraste
            blur = cv2.GaussianBlur(gray, (5, 5), 0)
            thresh = cv2.adaptiveThreshold(blur, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, 
                                         cv2.THRESH_BINARY_INV, 11, 2)
            
            # Configuração otimizada para placas de veículos
            custom_config = r'--oem 3 --psm 11 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789'
            text = pytesseract.image_to_string(thresh, config=custom_config, lang='por')
            
            # Processa o resultado para extrair a placa
            plate = ''.join(e for e in text if e.isalnum()).upper()
            
            if self.validate_plate(plate):
                return plate
            return None
        except Exception as e:
            st.error(f"Erro ao processar imagem: {str(e)}")
            return None

    def get_vehicle_info(self, plate):
        """Obtém informações do veículo e do proprietário"""
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT v.placa, v.modelo, v.marca, v.cor, v.tipo_veiculo,
                   c.nome, c.cargo, c.tag_id, c.foto
            FROM veiculos v
            LEFT JOIN colaboradores c ON v.colaborador_id = c.id
            WHERE v.placa = ?
        ''', (plate,))
        return cursor.fetchone()

    def register_access(self, plate, allowed, notes=""):
        """Registra um acesso no histórico"""
        cursor = self.conn.cursor()
        cursor.execute("SELECT id FROM veiculos WHERE placa = ?", (plate,))
        vehicle_id = cursor.fetchone()
        
        if vehicle_id:
            cursor.execute('''
                INSERT INTO acessos (veiculo_id, data_hora, acesso_permitido, observacoes)
                VALUES (?, ?, ?, ?)
            ''', (vehicle_id[0], datetime.now().strftime("%Y-%m-%d %H:%M:%S"), allowed, notes))
            self.conn.commit()
            return True
        return False

    def add_employee(self, name, position, tag_id, photo):
        """Cadastra um novo colaborador"""
        try:
            cursor = self.conn.cursor()
            cursor.execute('''
                INSERT INTO colaboradores (nome, cargo, tag_id, foto)
                VALUES (?, ?, ?, ?)
            ''', (name, position, tag_id, photo))
            self.conn.commit()
            return cursor.lastrowid
        except sqlite3.IntegrityError:
            st.error("Tag ID já cadastrada")
            return None

    def add_vehicle(self, plate, model, brand, color, employee_id, vehicle_type):
        """Cadastra um novo veículo"""
        if not self.validate_plate(plate):
            return False, "Placa inválida"
        
        try:
            cursor = self.conn.cursor()
            cursor.execute('''
                INSERT INTO veiculos (placa, modelo, marca, cor, colaborador_id, tipo_veiculo)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (plate.upper(), model, brand, color, employee_id, vehicle_type))
            self.conn.commit()
            return True, "Veículo cadastrado com sucesso"
        except sqlite3.IntegrityError:
            return False, "Placa já cadastrada"

    def get_access_report(self, start_date=None, end_date=None):
        """Gera relatório de acessos"""
        cursor = self.conn.cursor()
        
        query = '''
            SELECT a.data_hora, v.placa, v.modelo, v.marca, c.nome, c.cargo, 
                   CASE WHEN a.acesso_permitido THEN 'LIBERADO' ELSE 'NEGADO' END as status,
                   a.observacoes
            FROM acessos a
            JOIN veiculos v ON a.veiculo_id = v.id
            LEFT JOIN colaboradores c ON v.colaborador_id = c.id
        '''
        
        params = []
        if start_date and end_date:
            query += " WHERE date(a.data_hora) BETWEEN ? AND ?"
            params.extend([start_date, end_date])
        
        query += " ORDER BY a.data_hora DESC"
        
        cursor.execute(query, params)
        return cursor.fetchall()

# Inicializa o sistema
system = VehicleAccessSystem()

# Interface Streamlit
st.title("🚗 Sistema de Controle de Acesso - Carbon")

# Menu lateral
menu_option = st.sidebar.selectbox("Menu", ["Controle de Acesso", "Cadastros", "Relatórios", "Configurações"])

if menu_option == "Controle de Acesso":
    st.header("Registro de Acesso")
    
    tab1, tab2 = st.tabs(["Busca por Placa", "Reconhecimento por Imagem"])
    
    with tab1:
        plate_input = st.text_input("Digite a placa do veículo:").upper()
        if st.button("Consultar Placa"):
            if plate_input and system.validate_plate(plate_input):
                vehicle_info = system.get_vehicle_info(plate_input)
                if vehicle_info:
                    plate, model, brand, color, v_type, name, position, tag_id, photo = vehicle_info
                    
                    st.success("🚘 Veículo encontrado - Acesso LIBERADO")
                    
                    col1, col2 = st.columns(2)
                    
                    with col1:
                        st.subheader("Informações do Veículo")
                        st.write(f"**Placa:** {plate}")
                        st.write(f"**Modelo/Marca:** {model} / {brand}")
                        st.write(f"**Cor:** {color}")
                        st.write(f"**Tipo:** {v_type}")
                    
                    with col2:
                        st.subheader("Informações do Colaborador")
                        st.write(f"**Nome:** {name}")
                        st.write(f"**Cargo:** {position}")
                        st.write(f"**Tag ID:** {tag_id}")
                        
                        if photo:
                            st.image(Image.open(io.BytesIO(photo)), caption="Foto do Colaborador", width=150)
                    
                    system.register_access(plate, True)
                else:
                    st.error("⚠️ Veículo não cadastrado - Acesso NEGADO")
                    notes = st.text_input("Motivo da negação (opcional):")
                    if st.button("Confirmar Negação"):
                        system.register_access(plate_input, False, notes)
                        st.success("Registro de negação salvo!")
            else:
                st.warning("Formato de placa inválido. Use o padrão Mercosul (AAA0A00) ou antigo (AAA0000)")
    
    with tab2:
        uploaded_file = st.file_uploader("Capture/faça upload da imagem da placa:", type=["jpg", "png", "jpeg"])
        if uploaded_file:
            col1, col2 = st.columns(2)
            with col1:
                st.subheader("Imagem Original")
                st.image(uploaded_file, use_column_width=True)
            
            with col2:
                st.subheader("Processamento")
                with st.spinner("Processando imagem..."):
                    plate = system.recognize_plate(uploaded_file)
                
                if plate:
                    st.info(f"Placa identificada: {plate}")
                    vehicle_info = system.get_vehicle_info(plate)
                    
                    if vehicle_info:
                        plate, model, brand, color, v_type, name, position, tag_id, photo = vehicle_info
                        
                        st.success("🚘 Veículo encontrado - Acesso LIBERADO")
                        st.write(f"**Proprietário:** {name} ({position})")
                        
                        system.register_access(plate, True)
                    else:
                        st.error("⚠️ Veículo não cadastrado - Acesso NEGADO")
                        notes = st.text_input("Motivo da negação (opcional):")
                        if st.button("Confirmar Negação"):
                            system.register_access(plate, False, notes)
                            st.success("Registro de negação salvo!")
                else:
                    st.warning("Não foi possível identificar a placa na imagem")

elif menu_option == "Cadastros":
    st.header("Cadastros")
    
    tab1, tab2 = st.tabs(["Colaboradores", "Veículos"])
    
    with tab1:
        with st.expander("Cadastrar Novo Colaborador"):
            with st.form("employee_form"):
                st.subheader("Novo Colaborador")
                emp_name = st.text_input("Nome Completo*")
                emp_position = st.selectbox("Cargo*", ["Diretor", "Gerente", "Coordenador", "Analista", "Assistente", "Outro"])
                emp_tag = st.text_input("Número da Tag*")
                emp_photo = st.file_uploader("Foto do Colaborador", type=["jpg", "png", "jpeg"])
                
                submitted = st.form_submit_button("Cadastrar")
                if submitted:
                    if emp_name and emp_position and emp_tag:
                        photo_bytes = None
                        if emp_photo:
                            photo_bytes = emp_photo.read()
                        
                        employee_id = system.add_employee(emp_name, emp_position, emp_tag, photo_bytes)
                        if employee_id:
                            st.success("Colaborador cadastrado com sucesso!")
                    else:
                        st.error("Preencha todos os campos obrigatórios (*)")
        
        with st.expander("Lista de Colaboradores"):
            cursor = system.conn.cursor()
            cursor.execute("SELECT id, nome, cargo, tag_id FROM colaboradores WHERE ativo = 1")
            employees = cursor.fetchall()
            
            if employees:
                df_employees = pd.DataFrame(employees, columns=["ID", "Nome", "Cargo", "Tag ID"])
                st.dataframe(df_employees, use_container_width=True)
            else:
                st.info("Nenhum colaborador cadastrado")
    
    with tab2:
        with st.expander("Cadastrar Novo Veículo"):
            cursor = system.conn.cursor()
            cursor.execute("SELECT id, nome FROM colaboradores WHERE ativo = 1")
            employees = cursor.fetchall()
            employee_options = {f"{e[1]} (ID:{e[0]})": e[0] for e in employees}
            
            with st.form("vehicle_form"):
                st.subheader("Novo Veículo")
                vehicle_plate = st.text_input("Placa*").upper()
                vehicle_model = st.text_input("Modelo*")
                vehicle_brand = st.text_input("Marca*")
                vehicle_color = st.text_input("Cor*")
                vehicle_type = st.selectbox("Tipo de Veículo*", ["Diretor", "Gerente", "Funcionario", "Visitante"])
                vehicle_owner = st.selectbox("Proprietário*", options=list(employee_options.keys()))
                
                submitted = st.form_submit_button("Cadastrar")
                if submitted:
                    if all([vehicle_plate, vehicle_model, vehicle_brand, vehicle_color, vehicle_owner]):
                        owner_id = employee_options[vehicle_owner]
                        success, message = system.add_vehicle(
                            vehicle_plate, vehicle_model, vehicle_brand, 
                            vehicle_color, owner_id, vehicle_type
                        )
                        if success:
                            st.success(message)
                        else:
                            st.error(message)
                    else:
                        st.error("Preencha todos os campos obrigatórios (*)")
        
        with st.expander("Lista de Veículos"):
            cursor = system.conn.cursor()
            cursor.execute('''
                SELECT v.placa, v.modelo, v.marca, v.cor, v.tipo_veiculo, c.nome 
                FROM veiculos v
                LEFT JOIN colaboradores c ON v.colaborador_id = c.id
            ''')
            vehicles = cursor.fetchall()
            
            if vehicles:
                df_vehicles = pd.DataFrame(vehicles, columns=["Placa", "Modelo", "Marca", "Cor", "Tipo", "Proprietário"])
                st.dataframe(df_vehicles, use_container_width=True)
            else:
                st.info("Nenhum veículo cadastrado")

elif menu_option == "Relatórios":
    st.header("Relatórios de Acesso")
    
    col1, col2 = st.columns(2)
    with col1:
        start_date = st.date_input("Data inicial")
    with col2:
        end_date = st.date_input("Data final")
    
    if st.button("Gerar Relatório"):
        data = system.get_access_report(start_date, end_date)
        
        if data:
            df = pd.DataFrame(data, columns=["Data/Hora", "Placa", "Modelo", "Marca", "Proprietário", "Cargo", "Status", "Observações"])
            
            st.subheader("Dados de Acesso")
            st.dataframe(df, use_container_width=True)
            
            # Estatísticas
            st.subheader("Estatísticas")
            total = len(df)
            allowed = len(df[df['Status'] == 'LIBERADO'])
            denied = total - allowed
            
            col1, col2 = st.columns(2)
            col1.metric("Total de Acessos", total)
            col2.metric("Taxa de Liberação", f"{allowed/total*100:.1f}%")
            
            # Download
            csv = df.to_csv(index=False).encode('utf-8')
            st.download_button(
                "Baixar como CSV",
                data=csv,
                file_name=f"relatorio_acessos_{start_date}_{end_date}.csv",
                mime="text/csv"
            )
        else:
            st.info("Nenhum registro de acesso encontrado no período")

elif menu_option == "Configurações":
    st.header("Configurações do Sistema")
    
    with st.expander("Banco de Dados"):
        st.warning("Área restrita - Operações críticas")
        
        if st.button("Criar/Resetar Banco de Dados"):
            system.create_database()
            st.success("Banco de dados inicializado com sucesso!")
        
        if st.button("Fazer Backup do Banco"):
            with open('carbon_access.db', 'rb') as f:
                db_bytes = f.read()
            st.download_button(
                "Baixar Backup",
                data=db_bytes,
                file_name="backup_controle_acesso.db",
                mime="application/octet-stream"
            )
    
    with st.expander("Sobre"):
        st.write("""
        **Sistema de Controle de Acesso Carbon**  
        Versão 2.0  
        Desenvolvido para gestão de acessos veiculares  
        © 2023 Carbon Systems
        """)