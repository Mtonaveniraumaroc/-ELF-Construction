import os, io, csv, secrets, hashlib, json
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from functools import wraps
from flask import Flask, request, render_template, redirect, url_for, flash, session, abort, send_file, Response
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import func, UniqueConstraint
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from openpyxl import load_workbook

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', secrets.token_hex(32))
db_url = os.getenv('DATABASE_URL', 'sqlite:///elf_local.db')
if db_url.startswith('postgres://'): db_url = 'postgresql://' + db_url[len('postgres://'):]
app.config['SQLALCHEMY_DATABASE_URI'] = db_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['MAX_CONTENT_LENGTH'] = 12 * 1024 * 1024
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_SECURE'] = os.getenv('COOKIE_SECURE', '0') == '1' or bool(os.getenv('RENDER'))
db = SQLAlchemy(app)

class User(db.Model):
    id=db.Column(db.Integer,primary_key=True)
    name=db.Column(db.String(120),nullable=False)
    email=db.Column(db.String(200),unique=True,nullable=False)
    password=db.Column(db.String(300),nullable=False)
    role=db.Column(db.String(20),nullable=False,default='gestionnaire')
    active=db.Column(db.Boolean,default=True)
    must_change=db.Column(db.Boolean,default=False)

class Party(db.Model):
    id=db.Column(db.Integer,primary_key=True)
    kind=db.Column(db.String(30),nullable=False)
    name=db.Column(db.String(200),nullable=False)
    notes=db.Column(db.Text,default='')

class Site(db.Model):
    id=db.Column(db.Integer,primary_key=True)
    name=db.Column(db.String(200),nullable=False)
    budget=db.Column(db.Numeric(15,2),default=0)
    archived=db.Column(db.Boolean,default=False)
    notes=db.Column(db.Text,default='')

class Entry(db.Model):
    id=db.Column(db.Integer,primary_key=True)
    kind=db.Column(db.String(50),nullable=False)
    date=db.Column(db.String(10),nullable=False)
    label=db.Column(db.String(250),nullable=False)
    amount=db.Column(db.Numeric(15,2),nullable=False)
    site_id=db.Column(db.Integer,db.ForeignKey('site.id'))
    party_id=db.Column(db.Integer,db.ForeignKey('party.id'))
    parent_id=db.Column(db.Integer,db.ForeignKey('entry.id'))
    status=db.Column(db.String(20),default='a_verifier')
    notes=db.Column(db.Text,default='')
    source_key=db.Column(db.String(64),unique=True)
    import_batch_id=db.Column(db.Integer,db.ForeignKey('import_batch.id'))
    cancelled=db.Column(db.Boolean,default=False)
    created_by=db.Column(db.Integer,db.ForeignKey('user.id'))
    created_at=db.Column(db.DateTime,default=lambda:datetime.now(timezone.utc))
    site=db.relationship('Site',foreign_keys=[site_id])
    party=db.relationship('Party',foreign_keys=[party_id])

class Audit(db.Model):
    id=db.Column(db.Integer,primary_key=True)
    at=db.Column(db.DateTime,default=lambda:datetime.now(timezone.utc))
    actor=db.Column(db.Integer)
    action=db.Column(db.String(50))
    target=db.Column(db.String(80))
    before=db.Column(db.Text)
    after=db.Column(db.Text)

class Attachment(db.Model):
    id=db.Column(db.Integer,primary_key=True)
    entry_id=db.Column(db.Integer,db.ForeignKey('entry.id'),nullable=True)
    filename=db.Column(db.String(200),nullable=False)
    mime=db.Column(db.String(100),nullable=False)
    data=db.Column(db.LargeBinary,nullable=False)

class ImportBatch(db.Model):
    id=db.Column(db.Integer,primary_key=True)
    filename=db.Column(db.String(250))
    kind=db.Column(db.String(50))
    sheet=db.Column(db.String(100))
    count=db.Column(db.Integer,default=0)
    at=db.Column(db.DateTime,default=lambda:datetime.now(timezone.utc))
    actor=db.Column(db.Integer)

KINDS={
 'devis':'Devis client', 'avenant':'Avenant au devis', 'recette':'Paiement client reçu',
 'commande':'Bon de commande fournisseur', 'reglement':'Règlement fournisseur',
 'depense':'Dépense chantier hors commande', 'larbi_avance':'Avance Larbi à ELF',
 'larbi_remboursement':'Remboursement ELF à Larbi',
 'larbi_dette':'Dette fournisseur personnelle Larbi',
 'larbi_paiement':'Paiement dette personnelle Larbi'
}
PAYMENT_KINDS={'recette','reglement','larbi_remboursement','larbi_paiement'}
PARENTS={'recette':('devis','avenant'),'reglement':('commande',),'larbi_paiement':('larbi_dette',)}
STATUSES={'a_verifier':'À vérifier','verifie':'Vérifié','valide':'Validé'}

with app.app_context():
    db.create_all()
    admin_email=os.getenv('ADMIN_EMAIL','').strip().lower()
    admin_pw=os.getenv('ADMIN_PASSWORD','')
    if admin_email and admin_pw and not User.query.filter_by(email=admin_email).first():
        db.session.add(User(name='Administrateur ELF',email=admin_email,password=generate_password_hash(admin_pw),role='admin',must_change=True))
        db.session.commit()

def current():
    return db.session.get(User,session.get('uid')) if session.get('uid') else None

def logged(fn):
    @wraps(fn)
    def wrapper(*a,**k):
        u=current()
        if not u or not u.active: return redirect(url_for('login'))
        if u.must_change and request.endpoint not in ('change_password','logout'): return redirect(url_for('change_password'))
        return fn(*a,**k)
    return wrapper

def editable(fn):
    @wraps(fn)
    @logged
    def wrapper(*a,**k):
        if current().role not in ('admin','gestionnaire'): abort(403)
        return fn(*a,**k)
    return wrapper

def admin_only(fn):
    @wraps(fn)
    @logged
    def wrapper(*a,**k):
        if current().role!='admin': abort(403)
        return fn(*a,**k)
    return wrapper

@app.context_processor
def globals_ctx(): return dict(me=current(),kinds=KINDS,statuses=STATUSES)

@app.before_request
def csrf_guard():
    if request.method=='POST':
        if not session.get('csrf') or request.form.get('csrf')!=session.get('csrf'): abort(400,'Formulaire expiré, rechargez la page.')

@app.route('/login',methods=['GET','POST'])
def login():
    if request.method=='POST':
        u=User.query.filter_by(email=request.form.get('email','').strip().lower()).first()
        if u and u.active and check_password_hash(u.password,request.form.get('password','')):
            session.clear();session['uid']=u.id;session['csrf']=secrets.token_urlsafe(24)
            return redirect(url_for('index'))
        flash('Identifiants incorrects ou compte désactivé.','error')
    session.setdefault('csrf',secrets.token_urlsafe(24))
    return render_template('login.html')

@app.route('/logout')
def logout(): session.clear();return redirect(url_for('login'))

@app.route('/password',methods=['GET','POST'])
@logged
def change_password():
    if request.method=='POST':
        u=current();pw=request.form.get('password','')
        if len(pw)<12: flash('Choisissez au moins 12 caractères.','error')
        else:
            u.password=generate_password_hash(pw);u.must_change=False;db.session.commit()
            flash('Mot de passe mis à jour.','ok');return redirect(url_for('index'))
    return render_template('password.html')

def sums(kind):
    return Decimal(db.session.query(func.coalesce(func.sum(Entry.amount),0)).filter(Entry.kind==kind,Entry.cancelled==False).scalar())

def metrics():
    devis=sums('devis')+sums('avenant');received=sums('recette')
    orders=sums('commande');paid=sums('reglement')
    return dict(devis=devis,received=received,clients=devis-received,orders=orders,paid=paid,suppliers=orders-paid,
       expenses=sums('depense'),larbi_elf=sums('larbi_avance')-sums('larbi_remboursement'),
       larbi_personal=sums('larbi_dette')-sums('larbi_paiement'))

@app.route('/')
@logged
def index():
    entries=Entry.query.order_by(Entry.id.desc()).limit(15).all()
    return render_template('dashboard.html',m=metrics(),entries=entries)

@app.route('/entries')
@logged
def entries():
    kind=request.args.get('kind','')
    q=Entry.query
    if kind in KINDS:q=q.filter_by(kind=kind)
    return render_template('entries.html',entries=q.order_by(Entry.id.desc()).limit(600).all(),kind=kind)

def entry_payload(e):
    return {k:str(getattr(e,k)) for k in ('kind','date','label','amount','site_id','party_id','parent_id','status','notes','cancelled')}

def audit(action,target,before=None,after=None):
    db.session.add(Audit(actor=current().id,action=action,target=target,before=json.dumps(before,ensure_ascii=False) if before else None,after=json.dumps(after,ensure_ascii=False) if after else None))

def money(v):
    try:
        d=Decimal(str(v).replace(' ','').replace('\u00a0','').replace(',','.'))
        if d<=0 or d>Decimal('999999999999'): raise ValueError()
        return d.quantize(Decimal('0.01'))
    except (InvalidOperation,ValueError): raise ValueError('Montant invalide : saisir un montant positif.')

def optional_id(field,model):
    value=request.form.get(field,'').strip()
    if not value: return None
    n=int(value)
    if not db.session.get(model,n): raise ValueError('Référence introuvable.')
    return n

def fill_entry(e):
    kind=request.form.get('kind','')
    if kind not in KINDS: raise ValueError('Type d’opération invalide.')
    date=request.form.get('date','')
    datetime.strptime(date,'%Y-%m-%d')
    label=request.form.get('label','').strip()
    if not label: raise ValueError('Description obligatoire.')
    parent=optional_id('parent_id',Entry)
    if parent:
        p=db.session.get(Entry,parent)
        if kind not in PARENTS or p.kind not in PARENTS[kind] or p.cancelled: raise ValueError('Référence de paiement incompatible.')
    e.kind=kind;e.date=date;e.label=label;e.amount=money(request.form.get('amount',''))
    e.site_id=optional_id('site_id',Site);e.party_id=optional_id('party_id',Party)
    e.parent_id=parent;e.notes=request.form.get('notes','').strip()
    e.status=request.form.get('status','a_verifier')
    if e.status not in STATUSES: raise ValueError('Statut invalide.')

@app.route('/entry/new',methods=['GET','POST'])
@editable
def new_entry():
    if request.method=='POST':
        try:
            e=Entry(created_by=current().id);fill_entry(e)
            db.session.add(e);db.session.flush();audit('creation',f'operation:{e.id}',after=entry_payload(e));db.session.commit()
            flash('Opération enregistrée.','ok');return redirect(url_for('entries'))
        except (ValueError,TypeError) as exc:db.session.rollback();flash(str(exc),'error')
    return render_template('entry_form.html',entry=None,sites=Site.query.order_by(Site.name).all(),parties=Party.query.order_by(Party.name).all(),parents=Entry.query.filter_by(cancelled=False).order_by(Entry.id.desc()).limit(300).all())

@app.route('/entry/<int:ident>/edit',methods=['GET','POST'])
@editable
def edit_entry(ident):
    e=db.get_or_404(Entry,ident)
    if request.method=='POST':
        try:
            before=entry_payload(e);fill_entry(e)
            audit('modification',f'operation:{e.id}',before,entry_payload(e));db.session.commit()
            flash('Opération modifiée, historique conservé.','ok');return redirect(url_for('entries'))
        except (ValueError,TypeError) as exc:db.session.rollback();flash(str(exc),'error')
    return render_template('entry_form.html',entry=e,sites=Site.query.order_by(Site.name).all(),parties=Party.query.order_by(Party.name).all(),parents=Entry.query.filter_by(cancelled=False).order_by(Entry.id.desc()).limit(300).all(),attachments=Attachment.query.filter_by(entry_id=e.id).all())

@app.route('/entry/<int:ident>/cancel',methods=['POST'])
@editable
def cancel_entry(ident):
    e=db.get_or_404(Entry,ident);before=entry_payload(e);e.cancelled=not e.cancelled
    audit('annulation_ou_reactivation',f'operation:{e.id}',before,entry_payload(e));db.session.commit()
    flash('Statut de l’opération modifié.','ok');return redirect(url_for('entries'))

@app.route('/parties',methods=['GET','POST'])
@logged
def parties():
    if request.method=='POST':
        if current().role not in ('admin','gestionnaire'):abort(403)
        kind=request.form.get('kind');name=request.form.get('name','').strip()
        if kind in ('client','fournisseur') and name:
            p=Party(kind=kind,name=name,notes=request.form.get('notes',''));db.session.add(p);db.session.flush();audit('creation',f'tiers:{p.id}',after={'name':name,'kind':kind});db.session.commit();flash('Tiers ajouté.','ok')
        else:flash('Nom ou catégorie incorrecte.','error')
        return redirect(url_for('parties'))
    return render_template('parties.html',parties=Party.query.order_by(Party.kind,Party.name).all())

@app.route('/sites',methods=['GET','POST'])
@logged
def sites():
    if request.method=='POST':
        if current().role not in ('admin','gestionnaire'):abort(403)
        name=request.form.get('name','').strip()
        if name:
            s=Site(name=name,notes=request.form.get('notes',''));db.session.add(s);db.session.flush();audit('creation',f'chantier:{s.id}',after={'name':name});db.session.commit();flash('Chantier créé.','ok')
        return redirect(url_for('sites'))
    allsites=Site.query.order_by(Site.archived,Site.name).all()
    totals={}
    for s in allsites:
        rows=Entry.query.filter_by(site_id=s.id,cancelled=False).all()
        totals[s.id]={'recettes':sum((e.amount for e in rows if e.kind=='recette'),Decimal(0)),
          'commandes':sum((e.amount for e in rows if e.kind=='commande'),Decimal(0)),
          'depenses':sum((e.amount for e in rows if e.kind=='depense'),Decimal(0)),
          'reglements':sum((e.amount for e in rows if e.kind=='reglement'),Decimal(0))}
    return render_template('sites.html',sites=allsites,totals=totals)

@app.route('/site/<int:ident>/edit',methods=['POST'])
@editable
def edit_site(ident):
    s=db.get_or_404(Site,ident);before={'name':s.name,'budget':str(s.budget),'archived':s.archived}
    s.name=request.form.get('name',s.name).strip() or s.name
    try:s.budget=Decimal(request.form.get('budget','0').replace(',','.'))
    except InvalidOperation:abort(400)
    s.archived=request.form.get('archived')=='on'
    audit('modification',f'chantier:{s.id}',before,{'name':s.name,'budget':str(s.budget),'archived':s.archived});db.session.commit()
    return redirect(url_for('sites'))

@app.route('/entry/<int:ident>/attachment',methods=['POST'])
@editable
def add_attachment(ident):
    db.get_or_404(Entry,ident)
    f=request.files.get('file')
    if not f or not f.filename:abort(400)
    name=secure_filename(f.filename)
    ext=os.path.splitext(name)[1].lower()
    if ext not in ('.pdf','.jpg','.jpeg','.png','.webp'):abort(400,'PDF ou image uniquement.')
    data=f.read()
    if len(data)>8*1024*1024:abort(400,'Fichier trop volumineux.')
    a=Attachment(entry_id=ident,filename=name,mime={'pdf':'application/pdf'}.get(ext.lstrip('.'),'image/'+ext.lstrip('.').replace('jpg','jpeg')),data=data)
    db.session.add(a);db.session.flush();audit('piece_jointe',f'operation:{ident}',after={'filename':name,'attachment_id':a.id});db.session.commit()
    flash('Justificatif ajouté.','ok');return redirect(url_for('edit_entry',ident=ident))

@app.route('/attachment/<int:ident>')
@logged
def attachment(ident):
    a=db.get_or_404(Attachment,ident)
    return send_file(io.BytesIO(a.data),mimetype=a.mime,as_attachment=True,download_name=a.filename)

@app.route('/users',methods=['GET','POST'])
@admin_only
def users():
    if request.method=='POST':
        email=request.form.get('email','').strip().lower();name=request.form.get('name','').strip()
        role=request.form.get('role','gestionnaire');pw=request.form.get('password','')
        if role not in ('admin','gestionnaire','direction') or not name or '@' not in email or len(pw)<12 or User.query.filter_by(email=email).first():
            flash('Vérifier le nom, l’adresse, le rôle et le mot de passe temporaire (12 caractères minimum).','error')
        else:
            u=User(name=name,email=email,role=role,password=generate_password_hash(pw),must_change=True)
            db.session.add(u);db.session.flush();audit('creation',f'utilisateur:{u.id}',after={'email':email,'role':role});db.session.commit();flash('Compte créé. Communiquez le mot de passe temporaire hors de cette application.','ok')
        return redirect(url_for('users'))
    return render_template('users.html',users=User.query.order_by(User.id).all())

@app.route('/user/<int:ident>/toggle',methods=['POST'])
@admin_only
def toggle_user(ident):
    u=db.get_or_404(User,ident)
    if u.id==current().id:abort(400,'Impossible de désactiver son propre compte.')
    u.active=not u.active;audit('activation',f'utilisateur:{u.id}',after={'active':u.active});db.session.commit()
    return redirect(url_for('users'))

@app.route('/audit')
@admin_only
def history():return render_template('audit.html',rows=Audit.query.order_by(Audit.id.desc()).limit(500).all())

@app.route('/export')
@logged
def export():
    output=io.StringIO();w=csv.writer(output);w.writerow(['ID','Type','Date','Description','Montant DH','Chantier','Tiers','Référence','Statut','Annulée','Notes'])
    for e in Entry.query.order_by(Entry.id):
        w.writerow([e.id,e.kind,e.date,e.label,str(e.amount),e.site.name if e.site else '',e.party.name if e.party else '',e.parent_id or '',e.status,e.cancelled,e.notes])
    data='\ufeff'+output.getvalue()
    return Response(data,mimetype='text/csv; charset=utf-8',headers={'Content-Disposition':'attachment; filename=elf_export_operations.csv'})

# Import: explicitly preview and map columns. No automatic interpretation of payment status.
def spreadsheet_rows(data,sheet):
    wb=load_workbook(io.BytesIO(data),read_only=True,data_only=True)
    if sheet not in wb.sheetnames:raise ValueError('Feuille introuvable.')
    rows=list(wb[sheet].iter_rows(values_only=True))
    if len(rows)>3000:raise ValueError('Maximum 3000 lignes par import.')
    return [[str(v).strip() if v is not None else '' for v in row] for row in rows]

@app.route('/import',methods=['GET','POST'])
@editable
def import_excel():
    if request.method=='POST' and request.form.get('action')=='preview':
        f=request.files.get('file');kind=request.form.get('kind')
        if not f or not f.filename.lower().endswith('.xlsx') or kind not in KINDS:
            flash('Sélectionnez un fichier XLSX et un type d’opération.','error');return redirect(url_for('import_excel'))
        data=f.read()
        try:
            wb=load_workbook(io.BytesIO(data),read_only=True,data_only=True)
            sheet=request.form.get('sheet') or wb.sheetnames[0]
            rows=spreadsheet_rows(data,sheet)
            if len(rows)<2:raise ValueError('Fichier vide ou sans lignes de données.')
            token=secrets.token_urlsafe(20)
            # Staging in DB rather than cookie; persistent across Render instances.
            batch=ImportBatch(filename=secure_filename(f.filename),kind=kind,sheet=sheet,actor=current().id,count=0)
            db.session.add(batch);db.session.flush()
            # Store staging in an attachment-like DB blob, not local disk.
            a=Attachment(entry_id=None,filename='staging_'+token,mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',data=data)
            db.session.add(a);db.session.commit()
            session['import_staging']={'attachment':a.id,'batch':batch.id,'kind':kind,'sheet':sheet,'token':token}
            return render_template('import_preview.html',rows=rows[:11],columns=list(enumerate(rows[0])),kind=kind,sheet=sheet,filename=f.filename,sites_for_import=Site.query.order_by(Site.name).all())
        except Exception as exc:db.session.rollback();flash('Import impossible : '+str(exc),'error');return redirect(url_for('import_excel'))
    if request.method=='POST' and request.form.get('action')=='confirm':
        st=session.get('import_staging')
        if not st:abort(400,'Prévisualisation expirée.')
        a=db.session.get(Attachment,st['attachment']);batch=db.session.get(ImportBatch,st['batch'])
        if not a or not batch or batch.actor!=current().id:abort(400)
        try:
            rows=spreadsheet_rows(a.data,st['sheet']);indices={field:int(request.form[field]) for field in ('date','label','amount')}
            if len(set(indices.values()))!=3:raise ValueError('Les colonnes doivent être distinctes.')
            site_id=optional_id('site_id',Site)
            count=0;skipped=0;invalid=[]
            for line,row in enumerate(rows[1:],2):
                if not any(row):continue
                try:
                    date=row[indices['date']][:10];datetime.strptime(date,'%Y-%m-%d')
                    label=row[indices['label']].strip();amount=money(row[indices['amount']])
                    if not label:raise ValueError('Description manquante')
                    key=hashlib.sha256((hashlib.sha256(a.data).hexdigest()+'|'+st['sheet']+'|'+str(line)+'|'+st['kind']).encode()).hexdigest()
                    if Entry.query.filter_by(source_key=key).first():skipped+=1;continue
                    e=Entry(kind=st['kind'],date=date,label=label,amount=amount,site_id=site_id,status='a_verifier',created_by=current().id,source_key=key,import_batch_id=batch.id,notes=f"Import : {batch.filename} / {st['sheet']} / ligne {line}")
                    db.session.add(e);count+=1
                except Exception as exc:invalid.append(f'Ligne {line}: {exc}')
            if invalid:
                db.session.rollback();flash('Aucune ligne importée. Corriger le fichier : '+' ; '.join(invalid[:8]),'error');return redirect(url_for('import_excel'))
            batch.count=count  # original XLSX preserved in DB
            audit('import',f'import:{batch.id}',after={'filename':batch.filename,'count':count,'duplicates':skipped,'kind':st['kind']})
            db.session.commit();session.pop('import_staging',None)
            flash(f'Import terminé : {count} opérations, {skipped} doublons ignorés. Statut À vérifier.','ok');return redirect(url_for('entries'))
        except Exception as exc:db.session.rollback();flash('Import annulé : '+str(exc),'error');return redirect(url_for('import_excel'))
    return render_template('import.html')

@app.route('/import/<int:ident>/undo',methods=['POST'])
@admin_only
def undo_import(ident):
    batch=db.get_or_404(ImportBatch,ident)
    # Undo by exact provenance prefix; retain audit trail, soft cancel.
    entries=Entry.query.filter_by(import_batch_id=batch.id,cancelled=False).all()
    for e in entries:
        before=entry_payload(e);e.cancelled=True;audit('annulation_import',f'operation:{e.id}',before,entry_payload(e))
    db.session.commit();flash(f'{len(entries)} opérations annulées (historique conservé).','ok');return redirect(url_for('imports'))

@app.route('/imports')
@logged
def imports():return render_template('imports.html',batches=ImportBatch.query.filter(ImportBatch.count>0).order_by(ImportBatch.id.desc()).all())

@app.route('/health')
def health():return {'status':'ok'}

if __name__=='__main__':app.run(debug=os.getenv('FLASK_DEBUG')=='1',port=int(os.getenv('PORT',5000)))
