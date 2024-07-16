# Generated by Django 5.0.6 on 2024-05-21 21:51

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("recap", "0013_processingqueue_update"),
    ]

    operations = [
        migrations.AlterField(
            model_name="pacerhtmlfiles",
            name="upload_type",
            field=models.SmallIntegerField(
                choices=[
                    (1, "HTML Docket"),
                    (2, "HTML attachment page"),
                    (3, "PDF"),
                    (4, "Docket history report"),
                    (5, "Appellate HTML docket"),
                    (6, "Appellate HTML attachment page"),
                    (7, "Internet Archive XML docket"),
                    (8, "Case report (iquery.pl) page"),
                    (9, "Claims register page"),
                    (10, "Zip archive of RECAP Documents"),
                    (11, "Email in the SES storage format"),
                    (12, "Case query page"),
                    (13, "Appellate Case query page"),
                    (14, "Case query result page"),
                    (15, "Appellate Case query result page"),
                    (16, "ACMS docket JSON object"),
                    (17, "ACMS attachmente page JSON object"),
                ],
                help_text="The type of object that is uploaded",
            ),
        ),
        migrations.AlterField(
            model_name="processingqueue",
            name="upload_type",
            field=models.SmallIntegerField(
                choices=[
                    (1, "HTML Docket"),
                    (2, "HTML attachment page"),
                    (3, "PDF"),
                    (4, "Docket history report"),
                    (5, "Appellate HTML docket"),
                    (6, "Appellate HTML attachment page"),
                    (7, "Internet Archive XML docket"),
                    (8, "Case report (iquery.pl) page"),
                    (9, "Claims register page"),
                    (10, "Zip archive of RECAP Documents"),
                    (11, "Email in the SES storage format"),
                    (12, "Case query page"),
                    (13, "Appellate Case query page"),
                    (14, "Case query result page"),
                    (15, "Appellate Case query result page"),
                    (16, "ACMS docket JSON object"),
                    (17, "ACMS attachmente page JSON object"),
                ],
                help_text="The type of object that is uploaded",
            ),
        ),
    ]