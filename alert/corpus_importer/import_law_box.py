import os
import sys

execfile('/etc/courtlistener')
sys.path.append(INSTALL_ROOT)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "alert.settings")

from juriscraper.lib.string_utils import clean_string, harmonize, titlecase
from juriscraper.lib import parse_dates
import os
import pickle
import random
import re
import subprocess
import traceback
from django.utils.timezone import now
from lxml import html
from alert.citations.constants import EDITIONS, REPORTERS
from alert.citations.find_citations import get_citations
from datetime import date, timedelta
from alert.corpus_importer.court_regexes import fd_pairs, state_pairs
from alert.corpus_importer.judge_extractor import get_judge_from_str
from alert.lib.import_lib import map_citations_to_models

os.environ['DJANGO_SETTINGS_MODULE'] = 'alert.settings'

import argparse
import datetime
import fnmatch
import hashlib
from lxml.html.clean import Cleaner
from lxml.html import tostring

from alert.search.models import Document, Citation, Court


DEBUG = 'out'

try:
    with open('lawbox_fix_file.pkl', 'rb') as fix_file:
        fixes = pickle.load(fix_file)
except (IOError, EOFError):
    fixes = {}

try:
    # Load up SCOTUS dates
    scotus_dates = {}
    with open('../../cleaning_scripts/SupremeCourtCleanup/date_of_decisions.csv') as scotus_date_file:
        for line in scotus_date_file:
            line_parts = [line.strip() for line in line.split('|')]
            if line_parts[-1]:
                scotus_dates[line_parts[0]] = datetime.datetime.strptime(line_parts[-1].strip(), '%Y-%m-%d').date()
except IOError:
    pass


##########################################
# This variable is used to do statistical work on Opinions whose jurisdiction is unclear. The problem is that
# many Opinions, probably thousands of them, have a court like, "D. Wisconsin." Well, Wisconsin has an east and
# west district, but no generic district, so this has to be resolved. When we hit such a case, we set it aside
# for later processing, once we've processed all the easy cases. At that point, we will have the variable below,
# judge stats, which will have all of the judges along with a count of their jurisdictions:
# judge_stats = {
#     'McKensey': {
#         'wied': 998,
#         'wis': 2
#     }
# }
# So in this case, you can see quite clearly that McKensey is a judge at wied, and we can classify the case as
# such.
##########################################
judge_stats = {}

all_courts = Court.objects.all()

def add_fix(case_path, fix_dict):
    """Adds a fix to the fix dictionary. This dictionary looks like:

    fixes = {
        'path/to/some/case.html': {'docket_number': None, 'date_filed': date(1982, 6, 9)},
    }
    """
    if case_path in fixes:
        fixes[case_path].update(fix_dict)
    else:
        fixes[case_path] = fix_dict


def get_citations_from_tree(complete_html_tree):
    path = '//center[descendant::text()[not(starts-with(normalize-space(.), "No.") or starts-with(normalize-space(.), "Case No.") or starts-with(normalize-space(.), "Record No."))]]'
    citations = []
    for e in complete_html_tree.xpath(path):
        text = tostring(e, method='text', encoding='unicode')
        citations.extend(get_citations(text, html=False, do_defendant=False))
    if not citations:
        path = '//title/text()'
        text = complete_html_tree.xpath(path)[0]
        citations = get_citations(text, html=False, do_post_citation=False, do_defendant=False)
        if not citations:
            raise
    if DEBUG >= 3:
        cite_strs = [str(cite.__dict__) for cite in citations]
        print "  Citations found: %s" % ',\n                   '.join(cite_strs)

    return citations


def get_case_name(complete_html_tree):
    path = '//head/title/text()'
    # Text looks like: 'In re 221A Holding Corp., Inc, 1 BR 506 - Dist. Court, ED Pennsylvania 1979'
    s = complete_html_tree.xpath(path)[0].rsplit('-', 1)[0].rsplit(',', 1)[0]
    # returns 'In re 221A Holding Corp., Inc.'
    s = harmonize(clean_string(titlecase(s)))
    if DEBUG >= 3:
        print "  Case name: %s" % s
    return s


def get_date_filed(clean_html_tree, citations, case_path=None, court=None):
    if not scotus_dates:
        print "Failed to load scotus dates."
    path = '//center[descendant::text()[not(starts-with(normalize-space(.), "No.") or starts-with(normalize-space(.), "Case No.") or starts-with(normalize-space(.), "Record No."))]]'

    reporter_keys = [citation.reporter for citation in citations]
    range_dates = []
    for reporter_key in reporter_keys:
        for reporter in REPORTERS.get(EDITIONS.get(reporter_key)):
            try:
                range_dates.extend(reporter['editions'][reporter_key])
            except KeyError:
                # Fails when a reporter_key points to more than one reporter, one of which doesn't have the edition
                # queried. For example, Wash. 2d isn't in REPORTERS['Wash.']['editions'][0].
                pass
    if range_dates:
        start, end = min(range_dates) - timedelta(weeks=(20 * 52)), max(range_dates) + timedelta(weeks=20 * 52)
        if end > now():
            end = now()

    dates = []
    for e in clean_html_tree.xpath(path):
        text = tostring(e, method='text', encoding='unicode')
        # Items like "February 4, 1991, at 9:05 A.M." stump the lexer in the date parser. Consequently, we purge
        # the word at, and anything after it.
        text = re.sub(' at .*', '', text)
        try:
            if range_dates:
                found = parse_dates.parse_dates(text, sane_start=start, sane_end=end)
            else:
                found = parse_dates.parse_dates(text, sane_end=now())
            if found:
                dates.extend(found)
        except UnicodeEncodeError:
            # If it has unicode is crashes dateutil's parser, but is unlikely to be the date.
            pass

    # Get the date from our SCOTUS date table
    if not dates and court == 'scotus':
        for citation in citations:
            try:
                dates.append(scotus_dates["%s %s %s" % (citation.volume, citation.reporter, citation.page)])
            except KeyError:
                pass

    if not dates:
        # Try to grab the year from the citations, if it's the same in all of them.
        years = set([citation.year for citation in citations if citation.year])
        if len(years) == 1:
            dates.append(date(list(years)[0], 1, 1))

    if not dates:
        try:
            dates = fixes[case_path]['dates']
        except KeyError:
            if DEBUG >= 4:
                subprocess.Popen(['firefox', 'file://%s' % case_path], shell=False).communicate()
                input_date = raw_input('  No date found. What should be here (YYYY-MM-DD)? ')
                add_fix(case_path, {'dates': [datetime.datetime.strptime(input_date, '%Y-%m-%d').date()]})
                dates = [input_date]
            elif DEBUG == 2:
                # Write the failed case out to file.
                dates.append(now())
                with open('missing_dates.txt', 'a') as out:
                    out.write('%s\n' % case_path)

    if DEBUG >= 3:
        print "  Using date: %s of dates found: %s" % (max(dates), dates)
    return max(dates)


def get_precedential_status(html_tree):
    return None


def get_docket_number(html, case_path=None, court=None):
    try:
        path = '//center/text()'
        text_elements = html.xpath(path)
    except AttributeError:
        # Not an HTML element, instead it's a string
        text_elements = [html]
    docket_no_formats = ['Bankruptcy', 'C.A.', 'Case', 'Civ', 'Civil', 'Civil Action', 'Crim', 'Criminal Action',
                         'Docket', 'Misc', 'Record']
    regexes = [
        re.compile('((%s)( Nos?\.)?)|(Nos?(\.| )?)' % "|".join(map(re.escape, docket_no_formats)), re.IGNORECASE),
        re.compile('\d{2}-\d{2,5}'),          # WY-03-071, 01-21574
        re.compile('[A-Z]{2}-[A-Z]{2}'),      # CA-CR 5158
        re.compile('[A-Z]\d{2} \d{4}[A-Z]'),  # C86 1392M
        re.compile('\d{2} [A-Z] \d{4}'),      # 88 C 4330
        re.compile('[A-Z]-\d{2,4}'),          # M-47B (VLB), S-5408
        re.compile('[A-Z]\d{3,}',),
        re.compile('[A-Z]{4,}'),              # SCBD #4983
        re.compile('\d{5,}'),                 # 95816
        re.compile('\d{2},\d{3}'),            # 86,782
        re.compile('([A-Z]\.){4}'),           # S.C.B.D. 3020
        re.compile('\d{2}-[a-z]{2}-\d{4}'),
    ]

    docket_number = None
    outer_break = False
    for t in text_elements:
        if outer_break:
            # Allows breaking the outer loop from the inner loop
            break
        t = clean_string(t).strip('.')
        for regex in regexes:
            if re.search(regex, t):
                docket_number = t
                outer_break = True
                break

    if docket_number:
        if docket_number.startswith('No.'):
            docket_number = docket_number[4:]
        elif docket_number.startswith('Nos.'):
            docket_number = docket_number[5:]
        elif docket_number.startswith('Docket No.'):
            docket_number = docket_number[11:]
        if re.search('^\(.*\)$', docket_number):
            # Starts and ends with parens. Nuke 'em.
            docket_number = docket_number[1:-1]

    if docket_number and re.search('submitted|reversed', docket_number, re.I):
        # False positive. Happens when there's no docket number and the date is incorrectly interpretted.
        docket_number = None

    if not docket_number:
        try:
            docket_number = fixes[case_path]['docket_number']
        except KeyError:
            docket_number = None
            '''
            if 'northeastern' not in case_path and \
                    'federal_reporter/2d' not in case_path and \
                    court not in ['or', 'orctapp', 'cal'] and \
                    ('unsorted' not in case_path and court not in ['ind']) and \
                    ('pacific_reporter/2d' not in case_path and court not in ['calctapp']):
                # Lots of missing docket numbers here.
                if DEBUG >= 2:
                    subprocess.Popen(['firefox', 'file://%s' % case_path], shell=False).communicate()
                input_doc_number = raw_input('  No docket number found. What should be here? ')
                add_fix(case_path, {'docket_number': input_doc_number})
            '''
    if DEBUG >= 2:
        print '  Docket Number: %s' % docket_number
    return docket_number


def get_court_object(html, citations=None, case_path=None):
    """
       Parse out the court string, somehow, and then map it back to our internal ids
    """
    path = '//center/p/b/text()'
    text_elements = html.xpath(path)

    def string_to_key(str):
        """Given a string, tries to map it to a court key."""
        # State
        for regex, value in state_pairs:
            if re.search(regex, str):
                return value

        # Supreme Court
        if re.search('Supreme Court of (the )?United States', str) or \
            re.search('United States Supreme Court', str):
            return 'scotus'

        # Federal appeals
        if re.search('Court,? of Appeal', str) or \
                'Circuit of Appeals' in str:
            if 'First Circuit' in str or \
                    'First District' in str:
                return 'ca1'
            elif 'Second Circuit' in str or \
                    'Second District' in str:
                return 'ca2'
            elif 'Third Circuit' in str:
                return 'ca3'
            elif 'Fourth Circuit' in str:
                return 'ca4'
            elif 'Fifth Circuit' in str:
                return 'ca5'
            elif 'Sixth Circuit' in str:
                return 'ca6'
            elif 'Seventh Circuit' in str:
                return 'ca7'
            elif 'Eighth' in str:  # Aka, apparently, "Eighth Court"
                return 'ca8'
            elif re.search('Ninth (Judicial )?Circuit', str):
                return 'ca9'
            elif 'Tenth Circuit' in str:
                return 'ca10'
            elif 'Eleventh Circuit' in str:
                return 'ca11'
            elif 'District of Columbia' in str:
                return 'cadc'
            elif 'Federal Circuit' in str:
                return 'cafc'
            elif 'Emergency' in str:
                return 'eca'
            elif 'Court of Appeals of Columbia' in str:
                return 'cadc'
        elif 'Judicial Council of the Ninth Circuit' in str or \
                re.search('Ninth (Judicial )?Circuit', str):
            return 'ca9'

        # Federal district
        elif re.search('(^| )Distr?in?ct', str, re.I):
            for regex, value in fd_pairs:
                if re.search(regex, str):
                    return value
        elif 'D. Virgin Islands' in str:
            return 'vid'

        # Federal special
        elif 'United States Judicial Conference Committee' in str or \
                'U.S. Judicial Conference Committee' in str:
            return 'usjc'
        elif re.search('Judicial Panel ((on)|(of)) Multidistrict Litigation', str, re.I):
            return 'jpml'
        elif 'Court of Customs and Patent Appeals' in str:
            return 'ccpa'
        elif 'Court of Claims' in str:
            return 'cc'  # Cannot change
        elif 'United States Foreign Intelligence Surveillance Court' in str:
            return 'fiscr'  # Cannot change
        elif re.search('Court,? of,? International ?Trade', str):
            return 'cit'
        elif 'United States Customs Court' in str:
            return 'cusc'  # Cannot change?
        elif re.search('Special Court(\.|,)? Regional Rail Reorganization Act', str):
            return 'reglrailreorgct'

        # Bankruptcy Courts
        elif re.search('bankrup?tcy', str, re.I):
            # Bankruptcy Appellate Panels
            if re.search('Appellan?te Panel', str, re.I):
                if 'First Circuit' in str:
                    return 'bap1'
                elif 'Second Circuit' in str:
                    return 'bap2'
                elif 'Sixth Circuit' in str:
                    return 'bap6'
                elif 'Eighth Circuit' in str:
                    return 'bap8'
                elif 'Ninth Circuit' in str:
                    return 'bap9'
                elif 'Tenth Circuit' in str:
                    return 'bap10'
                elif 'Maine' in str:
                    return 'bapme'
                elif 'Massachusetts' in str:
                    return 'bapma'

            # Bankruptcy District Courts
            else:
                if 'District of Columbia' in str or \
                        'D. Columbia' in str:
                    return 'dcb'
                elif re.search('M(\.|(iddle))? ?D(\.|(istrict))? (of )?Alabama', str):
                    return 'almb'
                elif re.search('N\.? ?D(\.|(istrict))? (of )?Alabama', str):
                    return 'alnb'
                elif re.search('S\.? ?D(\.|(istrict))? (of )?Alabama', str):
                    return 'alsb'
                elif 'D. Alaska' in str:
                    return 'akb'
                elif re.search('D(\.|(istrict))? ?Arizona', str):
                    return 'arb'
                elif re.search('E\.? ?D(\.|(istrict))? ?(of )?Arkansas', str):
                    return 'areb'
                elif re.search('W\.? ?D(\.|(istrict))? ?(of )?Arkansas', str):
                    return 'arwb'
                elif re.search('C\.? ?D(\.|(istrict))? ?(of )?Cal(ifornia)?', str):
                    return 'cacb'
                elif re.search('E\.? ?D(\.|(istrict))? ?(of )?Cal(ifornia)?', str):
                    return 'caeb'
                elif re.search('N\.? ?D(\.|(istrict))? ?(of )?Cal(ifornia)?', str):
                    return 'canb'
                elif re.search('S\.? ?D(\.|(istrict))? ?(of )?Cal(ifornia)?', str):
                    return 'casb'
                elif re.search('D(\.|(istrict)) ?(of )?Colorado', str):
                    return 'cob'
                elif 'Connecticut' in str:
                    return 'ctb'
                elif re.search('D(\.|(istrict))? (of )?Delaware', str):
                    return 'deb'
                elif re.search('M\.? ?D(\.|(istrict))? ?(of )?Florida', str) or \
                        re.search('Middle District (of )?Florida', str) or \
                        'M .D. Florida' in str or \
                        'Florida, Tampa Division' in str or \
                        'Florida, Jacksonville Division' in str:
                    return 'flmb'
                elif re.search('N(\.|(orthern))? ?D(\.|(istrict))? (of )?Florida', str):
                    return 'flnb'
                elif re.search('S\. ?D(\.|(istrict))? (of )?Florida', str):
                    return 'flsb'
                elif re.search('M\.? ?D(\.|(istrict))? (of )?Georgia', str):
                    return 'gamb'
                elif re.search('N\.? ?D(\.|(istrict))? (of )?Georgia', str) or \
                        'Atlanta Division' in str:
                    return 'ganb'
                elif re.search('S\. ?D(\.|(istrict))? Georgia', str):
                    return 'gasb'
                elif re.search('D(\.|(istrict))? ?Hawai', str):
                    return 'hib'
                elif 'D. Idaho' in str:
                    return 'idb'
                elif re.search('C\.? ?D(\.|(istrict))? ?(of )?Ill(inois)?', str):
                    return 'ilcb'
                elif re.search('N\.? ?D(\.|(istrict))? ?(of )?Ill(inois)?', str):
                    return 'ilnb'
                elif re.search('S\.? ?D(\.|(istrict))? ?(of )?Ill(inois)?', str):
                    return 'ilsb'
                elif re.search('N\.? ?D(\.|(istrict))? ?(of )?Indiana', str):
                    return 'innb'
                elif re.search('S.D. (of )?Indiana', str):
                    return 'insb'
                elif re.search('N\. ?D(\.|(istrict))? Iowa', str):
                    return 'ianb'
                elif re.search('S\. ?D(\.|(istrict))? (of )?Iowa', str):
                    return 'iasb'
                elif 'D. Kansas' in str or \
                        'M. Kansas' in str or \
                        'District of Kansas' in str or \
                        'D. Kan' in str:
                    return 'ksb'
                elif re.search('E\.? ?D(\.|(istrict))? (of )?Kentucky', str):
                    return 'kyeb'
                elif re.search('W\.? ?D(\.|(istrict))? (of )?Kentucky', str):
                    return 'kywb'
                elif re.search('E\.? ?D(\.|(istrict))? (of )?Loui?siana', str) or \
                        'Eastern District, Louisiana' in str:
                    return 'laeb'
                elif re.search('M\.? ?D(\.|(istrict))? (of )?Loui?siana', str):
                    return 'lamb'
                elif re.search('W\.? ?D(\.|(istrict))? (of )?Loui?siana', str):
                    return 'lawb'
                elif 'D. Maine' in str:
                    return 'meb'
                elif 'Maryland' in str:
                    return 'mdb'
                elif re.search('D(\.|(istrict))? ?(of )?Mass', str) or \
                        ', Massachusetts' in str:
                    return 'mab'
                elif re.search('E\.? ?D(\.|(istrict))? (of )?Michigan', str):
                    return 'mieb'
                elif re.search('W\.D(\.|(istrict))? (of )?Michigan', str):
                    return 'miwb'
                elif re.search('D(\.|(istrict))? ?Minnesota', str):
                    return 'mnb'
                elif re.search('N\.? ?D(\.|(istrict))? (of )?Mississippi', str):
                    return 'msnb'
                elif re.search('S\.? ?D(\.|(istrict))? (of )?Mississippi', str):
                    return 'mssb'
                elif re.search('E\.? ?D(\.|(istrict))? ?(of )?Missouri', str):
                    return 'moeb'
                elif re.search('W\.? ?D(\.|(istrict))? ?(of )?Missouri', str):
                    return 'mowb'
                elif 'D. Montana' in str:
                    return 'mtb'
                # Here we avoid a conflict with state abbreviations
                elif re.search('D(\.|(istrict))? (of )?Neb(raska)?', str):
                    return 'nebraskab'
                elif 'Nevada' in str:
                    return 'nvb'
                elif 'New Hampshire' in str or \
                        'D.N.H' in str:
                    return 'nhb'
                elif re.search('D(\.|(istrict))? ?New Jersey', str) or \
                        ', New Jersey' in str:
                    return 'njb'
                elif 'New Mexico' in str or \
                        'State of New Mexico' in str:
                    return 'nmb'
                elif re.search('E\.? ?D(\.|(istrict))? (of )?New York', str) or \
                        'E.D.N.Y' in str:
                    return 'nyeb'
                elif re.search('N\.? ?D(\.|(istrict))? (of )?New York', str):
                    return 'nynb'
                elif re.search('S\. ?D(\.|(istrict))? (of )?New York', str) or \
                        'Southern District of New York' in str or \
                        'S.D.N.Y' in str:
                    return 'nysb'
                elif re.search('W\.? ?D(\.|(istrict))? (of )?New York', str):
                    return 'nywb'
                elif re.search('E\.? ?D(\.|(istrict))? (of )?North Carolina', str):
                    return 'nceb'
                elif re.search('M\.? ?D(\.|(istrict))? (of )?North Carolina', str):
                    return 'ncmb'
                elif re.search('W\.? ?D(\.|(istrict))? (of )?North Carolina', str):
                    return 'ncwb'
                elif 'North Dakota' in str:
                    return 'ndb'
                elif re.search('N\.? ?D(\.|(istrict))? (of )?Ohio', str) or \
                        'Northern District of Ohio' in str:
                    return 'ohnb'
                elif re.search('S\. ?D(\.|(istrict))? (of )?Ohio', str):
                    return 'ohsb'
                elif re.search('E\.? ?D(\.|(istrict))? (of )?Oklahoma', str):
                    return 'okeb'
                elif re.search('N\.? ?D(\.|(istrict))? (of )?Oklahoma', str):
                    return 'oknb'
                elif re.search('W\.? ?D(\.|(istrict))? (of )?Oklahoma', str):
                    return 'okwb'
                elif 'Oregon' in str:
                    return 'orb'
                elif re.search('E\.? ?D(\.|(istrict))? (of )?Pennsylvania', str):
                    return 'paeb'
                elif re.search('M\.? ?D(\.|(istrict))? (of )?Pennsylvania', str):
                    return 'pamb'
                elif re.search('W\.? ?D(\.|(istrict))? (of )?Pennsylvania', str):
                    return 'pawb'
                elif ', Rhode Island' in str or \
                        re.search('D(\.|(istrict))? ?Rhode Island', str) or \
                        ', D.R.I' in str:
                    return 'rib'
                elif 'D.S.C' in str or \
                        re.search('D(\.|(istrict))? ?(of )?South Carolina', str):
                    return 'scb'
                elif 'D. South Dakota' in str or \
                        ', South Dakota' in str:
                    return 'sdb'
                elif re.search('E\.? ?D(\.|(istrict))? (of )?Te(r|n)n(essee)?', str):
                    return 'tneb'
                elif re.search('M\.? ?D(\.|(istrict))? (of )?Tenn(essee)?', str) or \
                        'Middle District of Tennessee' in str or \
                        'M.D.S. Tennessee' in str or \
                        'Nashville' in str:
                    return 'tnmb'
                elif re.search('W\.? ?D(\.|(istrict))? (of )?Tennessee', str):
                    return 'tnwb'
                elif 'D. Tennessee' in str:
                    return 'tennesseeb'
                elif re.search('E\.? ?D(\.|(istrict))? (of )?Texas', str):
                    return 'txeb'
                elif re.search('N\.? ?D(\.|(istrict))? (of )?Texas', str):
                    return 'txnb'
                elif re.search('S\.? ?D(\.|(istrict))? (of )?Texas', str):
                    return 'txsb'
                elif re.search('W\.? ?D(\.|(istrict))? (of )?Texas', str):
                    return 'txwb'
                elif 'Utah' in str:
                    return 'utb'
                elif re.search('D(\.|(istrict))? ?(of )?Vermont', str):
                    return 'vtb'
                elif re.search('E\.? ?D(\.|(istrict))? ?(of )?Virginia', str):
                    return 'vaeb'
                elif re.search('W\.? ?D(\.|(istrict))? ?(of )?Virginia', str) or \
                        re.search('Big Stone Gap', str):
                    return 'vawb'
                elif re.search('E\.? ?D(\.|(istrict))? (of )?Washington', str):
                    return 'waeb'
                elif re.search('W\.? ?D(\.|(istrict))? (of )?Washington', str):
                    return 'wawb'
                elif re.search('N\.? ?D(\.|(istrict))? (of )?W(\.|(est)) Virginia', str):
                    return 'wvnb'
                elif re.search('S\.? ?D(\.|(istrict))? (of )?W(\.|(est)) Virginia', str):
                    return 'wvsb'
                elif re.search('E\.? ?D(\.|(istrict))? (of )?Wis(consin)?', str):
                    return 'wieb'
                elif re.search('W\.? ?D(\.|(istrict))? (of )?Wis(consin)?', str) or \
                        'Western District of Wisconsin' in str:
                    return 'wiwb'
                elif 'D. Wyoming' in str:
                    return 'wyb'
                elif 'Guam' in str:
                    return 'gub'
                elif 'Northern Mariana' in str:
                    return 'nmib'
                elif 'Puerto Rico' in str:
                    return 'prb'
                elif 'Virgin Islands' in str:
                    return 'vib'
        else:
            return False

    court = None
    for t in text_elements:
        t = clean_string(t).strip('.')
        court = string_to_key(t)
        if court:
            break

    # Round two: try the text elements joined together
    t = clean_string(' '.join(text_elements)).strip('.')
    court = string_to_key(t)

    if citations:
        # Round three: try using the citations as a clue
        reporter_keys = [citation.canonical_reporter for citation in citations]
        if 'Cal. Rptr.' in reporter_keys:
            # It's a california court.
            for t in text_elements:
                t = clean_string(t).strip('.')
                if re.search('court of appeal', t, re.I):
                    court = 'calctapp'

    if not court:
        try:
            court = fixes[case_path]['court']
        except KeyError:
            if DEBUG == 'firefox':
                subprocess.Popen(['firefox', 'file://%s' % case_path], shell=False).communicate()
                input_court = raw_input("No court identified! What should be here? ")
                add_fix(case_path, {'court': input_court})
            elif DEBUG == 'out':
                # Write the failed case out to file.
                court = 'test'
                with open('missing_courts_judge_generator.txt', 'a') as out:
                    out.write('%s\n' % case_path)

    if 'print' in DEBUG:
        print '  Court: %s' % court

    return court


def get_judge(html, case_path=None):
    path = '//p[position() <= 60]//text()[not(parent::span)][not(ancestor::center)][not(ancestor::i)]'
    text_elements = html.xpath(path)

    # Get the first paragraph that starts with two uppercase letters after we've stripped out any star pagination.
    judge = None
    for t in text_elements:
        t = clean_string(t)
        judge, reason = get_judge_from_str(t)
        if judge:
            break
        if reason == 'TOO_LONG':
            # We've begun doing paragraphs...
            break

    if not judge:
        if DEBUG == 'firefox':
            subprocess.Popen(['firefox', 'file://%s' % case_path], shell=False).communicate()
            input_judge = raw_input("No judge identified! What should be here? ")

    if 'print' in DEBUG:
        print '  Judge: %s' % judge

    return judge


def get_html_from_raw_text(raw_text):
    """Using the raw_text, creates four useful variables:
        1. complete_html_tree: A tree of the complete HTML from the file, including <head> tags and whatever else.
        2. clean_html_tree: A tree of the HTML after stripping bad stuff.
        3. clean_html_str: A str of the HTML after stripping bad stuff.
        4. body_text: A str of the text of the body of the document.

    We require all of these because sometimes we need the complete HTML tree, other times we don't. We create them all
    up front for performance reasons.
    """
    complete_html_tree = html.fromstring(raw_text)
    cleaner = Cleaner(style=True,
                      remove_tags=['a', 'body', 'font', 'noscript'])
    clean_html_str = cleaner.clean_html(raw_text)
    clean_html_tree = html.fromstring(clean_html_str)
    body_text = tostring(clean_html_tree, method='text', encoding='unicode')

    return clean_html_tree, complete_html_tree, clean_html_str, body_text


def import_law_box_case(case_path):
    """Open the file, get its contents, convert to XML and extract the meta data.

    Return a document object for saving in the database
    """
    raw_text = open(case_path).read()
    clean_html_tree, complete_html_tree, clean_html_str, body_text = get_html_from_raw_text(raw_text)

    sha1 = hashlib.sha1(clean_html_str).hexdigest()
    citations = get_citations_from_tree(complete_html_tree)
    judges = get_judge(clean_html_tree, case_path)
    court = get_court_object(clean_html_tree, citations, case_path)

    doc = Document(
        source='LB',
        sha1=sha1,
        court_id=court,
        html=clean_html_str,
        date_filed=get_date_filed(clean_html_tree, citations=citations, case_path=case_path, court=court),
        precedential_status=get_precedential_status(clean_html_tree),
        judges=judges,
    )

    cite = Citation(
        case_name=get_case_name(complete_html_tree),
        docket_number=get_docket_number(clean_html_tree, case_path=case_path, court=court)
    )

    # Add the dict of citations to the object as its attributes.
    citations_as_dict = map_citations_to_models(citations)
    for k, v in citations_as_dict.iteritems():
        setattr(cite, k, v)

    # TODO: I'm baffled why this isn't working right now.
    #doc.citation = cite

    return doc


def readable_dir(prospective_dir):
    if not os.path.isdir(prospective_dir):
        raise argparse.ArgumentTypeError("readable_dir:{0} is not a valid path".format(prospective_dir))
    if os.access(prospective_dir, os.R_OK):
        return prospective_dir
    else:
        raise argparse.ArgumentTypeError("readable_dir:{0} is not a readable dir".format(prospective_dir))


def check_duplicate(doc):
    """Return true if it should be saved, else False"""
    return True


def main():
    parser = argparse.ArgumentParser(description='Import the corpus provided by lawbox')
    parser.add_argument('-s', '--simulate', default=False, required=False, action='store_true',
                        help='Run the code in simulate mode, making no permanent changes.')
    parser.add_argument('-d', '--dir', type=readable_dir,
                        help='The directory where the lawbox dump can be found.')
    parser.add_argument('-f', '--file', type=str, default="index.txt", required=False, dest="file_name",
                        help="The file that has all the URLs to import, one per line.")
    parser.add_argument('-l', '--line', type=int, default=1, required=False,
                        help='If provided, this will be the line number in the index file where we resume processing.')
    parser.add_argument('-r', '--resume', default=False, required=False, action='store_true',
                        help='Use the saved marker to resume operation where it last failed.')
    parser.add_argument('-x', '--random', default=False, required=False, action='store_true',
                        help='Pick cases randomly rather than serially.')
    args = parser.parse_args()

    if args.dir:
        def case_generator(dir_root):
            """Yield cases, one by one to the importer by recursing and iterating the import directory"""
            for root, dirnames, filenames in os.walk(dir_root):
                for filename in fnmatch.filter(filenames, '*'):
                    yield os.path.join(root, filename)

        cases = case_generator(args.root)
        i = 0
    else:
        def generate_random_line(file_name):
            while True:
                total_bytes = os.stat(file_name).st_size
                random_point = random.randint( 0, total_bytes )
                f = open(file_name)
                f.seek(random_point)
                f.readline()  # skip this line to clear the partial line
                yield f.readline().strip()

        def case_generator(line_number):
            """Yield cases from the index file."""
            index_file = open(args.file_name)
            for i, line in enumerate(index_file):
                if i > line_number:
                    yield line.strip()

        if args.random:
            cases = generate_random_line(args.file_name)
            i = 0
        elif args.resume:
            with open('lawbox_progress_marker.txt') as marker:
                resume_point = int(marker.read().strip())
            cases = case_generator(resume_point)
            i = resume_point
        else:
            cases = case_generator(args.line)
            i = args.line

    for case_path in cases:
        if DEBUG >= 2:  #and i % 1000 == 0:
            print "\n%s: Doing case (%s): file://%s" % (datetime.datetime.now(), i, case_path)
        try:
            doc = import_law_box_case(case_path)
            i += 1
        finally:
            traceback.format_exc()
            with open('lawbox_progress_marker.txt', 'w') as marker:
                marker.write(str(i))
            with open('lawbox_fix_file.pkl', 'wb') as fix_file:
                pickle.dump(fixes, fix_file)


        save_it = check_duplicate(doc)  # Need to write this method?
        if save_it and not args.simulate:
            # Not a dup, save to disk, Solr, etc.
            doc.cite.save()  # I think this is the save routine?
            doc.save()  # Do we index it here, or does that happen automatically?


if __name__ == '__main__':
    main()
