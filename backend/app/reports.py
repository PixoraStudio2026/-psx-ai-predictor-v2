from pathlib import Path
from datetime import datetime, timezone
from sqlalchemy import select, desc
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
from .models import MarketBar, ModelRun, Prediction, NewsArticle

def build_daily_pdf(db):
    out=Path("reports"); out.mkdir(exist_ok=True)
    path=out/"daily-report.pdf"
    doc=SimpleDocTemplate(str(path),pagesize=A4)
    styles=getSampleStyleSheet(); story=[]
    story += [Paragraph("PSX AI Predictor — Educational Research Report",styles["Title"]),
        Paragraph(f"Generated: {datetime.now(timezone.utc).isoformat(timespec='seconds')}",styles["Normal"]),
        Spacer(1,12),
        Paragraph("Educational research and paper simulation only. Not investment advice. Imported data is not necessarily live or licensed for redistribution. Verify provider rights and timestamps.",styles["BodyText"]),Spacer(1,14)]
    rows=[["Symbol","Last close","Timestamp","Source","Synthetic"]]
    symbols=[x[0] for x in db.query(MarketBar.symbol).distinct().all()]
    for symbol in symbols[:30]:
        r=db.scalars(select(MarketBar).where(MarketBar.symbol==symbol).order_by(desc(MarketBar.timestamp)).limit(1)).first()
        rows.append([symbol,f"{r.close:.4f}",r.timestamp.isoformat(),r.source,str(r.simulated)])
    if len(rows)==1: rows.append(["—","No data imported","—","—","—"])
    t=Table(rows,repeatRows=1,colWidths=[55,65,150,100,55])
    t.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,0),colors.HexColor("#183448")),
        ("TEXTCOLOR",(0,0),(-1,0),colors.white),("GRID",(0,0),(-1,-1),.3,colors.lightgrey),
        ("FONTSIZE",(0,0),(-1,-1),7),("VALIGN",(0,0),(-1,-1),"TOP")]))
    story += [Paragraph("Latest imported market records",styles["Heading2"]),t,Spacer(1,14)]
    interval_rows=[["Interval","Latest timestamp (PSX local)","Source","Simulated"]]
    for interval in ["1d", "15m", "1h", "5m"]:
        latest_interval=db.scalars(select(MarketBar).where(MarketBar.interval==interval).order_by(desc(MarketBar.timestamp)).limit(1)).first()
        if latest_interval:
            interval_rows.append([interval,latest_interval.timestamp.isoformat(),latest_interval.source,str(latest_interval.simulated)])
    if len(interval_rows)==1: interval_rows.append(["—","No interval data","—","—"])
    it=Table(interval_rows,repeatRows=1,colWidths=[55,150,145,55])
    it.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,0),colors.HexColor("#183448")),("TEXTCOLOR",(0,0),(-1,0),colors.white),("GRID",(0,0),(-1,-1),.3,colors.lightgrey),("FONTSIZE",(0,0),(-1,-1),7)]))
    story += [Paragraph("Data coverage and provenance",styles["Heading2"]),it,Spacer(1,10),
        Paragraph("No PSX-wide index, macroeconomic regime, live-feed or delayed-feed provider is configured. This report therefore describes only imported stock records; it does not infer broad market conditions.",styles["BodyText"]),Spacer(1,12)]
    news_rows=[["Symbol","Headline","Source","Published (PSX local)"]]
    articles=db.scalars(select(NewsArticle).order_by(desc(NewsArticle.published_at)).limit(15)).all()
    for article in articles:
        news_rows.append([article.symbol or "Market",article.title[:100],article.source,article.published_at.isoformat()])
    if len(news_rows)==1: news_rows.append(["—","No news articles imported","—","—"])
    nt=Table(news_rows,repeatRows=1,colWidths=[48,190,85,105])
    nt.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,0),colors.HexColor("#183448")),("TEXTCOLOR",(0,0),(-1,0),colors.white),("GRID",(0,0),(-1,-1),.3,colors.lightgrey),("FONTSIZE",(0,0),(-1,-1),7),("VALIGN",(0,0),(-1,-1),"TOP")]))
    story += [Paragraph("Latest imported news (source-attributed)",styles["Heading2"]),nt,Spacer(1,14)]
    pred_rows=[["Symbol","Horizon","P(positive)","Gross %","Net %","Risk","Model version","Data as of"]]
    predictions=db.scalars(select(Prediction).order_by(desc(Prediction.data_as_of)).limit(30)).all()
    for p in predictions:
        pred_rows.append([p.symbol,"Intraday" if p.horizon==0 else "Next day",
            f"{p.probability_positive:.1%}",f"{p.expected_gross_return_pct:.2f}" if p.expected_gross_return_pct is not None else "—",
            f"{p.estimated_net_return_pct:.2f}" if p.estimated_net_return_pct is not None else "—",p.risk_level or "—",p.model_version,p.data_as_of.isoformat()])
    if len(pred_rows)==1: pred_rows.append(["—","No saved predictions","—","—","—","—","—","—"])
    pt=Table(pred_rows,repeatRows=1,colWidths=[42,48,48,42,42,38,90,95])
    pt.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,0),colors.HexColor("#183448")),
        ("TEXTCOLOR",(0,0),(-1,0),colors.white),("GRID",(0,0),(-1,-1),.3,colors.lightgrey),
        ("FONTSIZE",(0,0),(-1,-1),7),("VALIGN",(0,0),(-1,-1),"TOP")]))
    story += [Paragraph("Saved statistical predictions",styles["Heading2"]),pt,Spacer(1,12)]
    model_rows=[["Symbol","Horizon","Accuracy","Brier","Test N","Model version","Trained through"]]
    model_runs=db.scalars(select(ModelRun).order_by(desc(ModelRun.trained_at)).limit(20)).all()
    for m in model_runs:
        model_rows.append([m.symbol,"Intraday" if m.horizon==0 else "Next day",f"{m.accuracy:.1%}",f"{m.brier_score:.3f}",str(m.test_samples),m.model_version,(m.trained_through.isoformat() if m.trained_through else "—")])
    if len(model_rows)==1: model_rows.append(["—","No model runs","—","—","—","—","—"])
    mt=Table(model_rows,repeatRows=1,colWidths=[45,48,55,45,40,95,100])
    mt.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,0),colors.HexColor("#183448")),("TEXTCOLOR",(0,0),(-1,0),colors.white),("GRID",(0,0),(-1,-1),.3,colors.lightgrey),("FONTSIZE",(0,0),(-1,-1),7),("VALIGN",(0,0),(-1,-1),"TOP")]))
    story += [Paragraph("Model evaluation history",styles["Heading2"]),mt,Spacer(1,12)]
    story.append(Paragraph("Probabilities and historical metrics are uncertain and do not guarantee future results. Imported records are not necessarily live. Missing licensed feeds, point-in-time fundamentals or verified news are not inferred.",styles["BodyText"]))
    doc.build(story)
    return str(path)
