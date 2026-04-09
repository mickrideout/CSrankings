#!/usr/bin/env python3
"""
Find all Monash University researchers in AI fields from CSRankings data.
Outputs a comprehensive markdown report in Logseq-compatible format.
"""

import csv
import glob
import os
import lzma
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path


def load_faculty_data(data_dir: str) -> dict:
    """Load all faculty data from csrankings CSV files."""
    faculty = {}
    csv_files = glob.glob(os.path.join(data_dir, "csrankings-*.csv"))
    
    for csv_file in csv_files:
        with open(csv_file, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                name = row['name'].strip()
                faculty[name] = {
                    'name': name,
                    'affiliation': row['affiliation'].strip(),
                    'homepage': row['homepage'].strip(),
                    'scholar_id': row['scholarid'].strip() if 'scholarid' in row else '',
                    'orcid': row['orcid'].strip() if 'orcid' in row else ''
                }
    
    return faculty


def load_orcid_data(data_dir: str) -> dict:
    """Load ORCID mappings."""
    orcid_map = {}
    orcid_file = os.path.join(data_dir, "orcid.csv")
    
    if os.path.exists(orcid_file):
        with open(orcid_file, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                name = row['name'].strip()
                orcid = row['orcid'].strip()
                if orcid and orcid != '0000-0000-0000-0000':
                    orcid_map[name] = orcid
    
    return orcid_map


def load_aliases(data_dir: str) -> dict:
    """Load DBLP name aliases."""
    aliases = {}
    alias_file = os.path.join(data_dir, "dblp-aliases.csv")
    
    if os.path.exists(alias_file):
        with open(alias_file, 'r', encoding='utf-8') as f:
            reader = csv.reader(f)
            for row in reader:
                if len(row) >= 2:
                    canonical = row[0].strip()
                    alias = row[1].strip()
                    aliases[alias] = canonical
    
    return aliases


def load_institutions(data_dir: str) -> dict:
    """Load institution data."""
    institutions = {}
    inst_file = os.path.join(data_dir, "institutions.csv")
    
    with open(inst_file, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = row['institution'].strip()
            institutions[name] = {
                'region': row['region'].strip(),
                'country': row['countryabbrv'].strip(),
                'homepage': row['homepage'].strip() if 'homepage' in row else ''
            }
    
    return institutions


def load_publications(data_dir: str) -> list:
    """Load publication data."""
    pubs = []
    pub_file = os.path.join(data_dir, "generated-author-info.csv")
    
    with open(pub_file, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            pubs.append({
                'name': row['name'].strip(),
                'dept': row['dept'].strip(),
                'area': row['area'].strip(),
                'count': float(row['count']),
                'adjusted_count': float(row['adjustedcount']),
                'year': int(row['year'])
            })
    
    return pubs


def get_ai_areas():
    """Return AI research areas and their conferences."""
    ai_areas = {
        'ai': ['ai', 'aaai', 'ijcai'],
        'vision': ['vision', 'cvpr', 'eccv', 'iccv'],
        'mlmining': ['mlmining', 'icml', 'kdd', 'iclr', 'nips'],
        'nlp': ['nlp', 'acl', 'emnlp', 'naacl'],
        'inforet': ['inforet', 'sigir', 'www']
    }
    
    # Conference to area mapping (from CSRankings config)
    conf_to_area = {
        'aaai': 'ai', 'ijcai': 'ai',
        'cvpr': 'vision', 'eccv': 'vision', 'iccv': 'vision',
        'icml': 'mlmining', 'kdd': 'mlmining', 'iclr': 'mlmining', 'nips': 'mlmining', 'neurips': 'mlmining',
        'acl': 'nlp', 'emnlp': 'nlp', 'naacl': 'nlp',
        'sigir': 'inforet', 'www': 'inforet'
    }
    
    # Flatten to all AI area codes
    all_ai_areas = []
    for subareas in ai_areas.values():
        all_ai_areas.extend(subareas)
    
    return ai_areas, all_ai_areas, conf_to_area


def is_monash_affiliation(affiliation: str) -> bool:
    """Check if affiliation is Monash University."""
    monash_variants = [
        'Monash University',
        'Monash University Indonesia',
        'Monash University Malaysia'
    ]
    return any(variant in affiliation for variant in monash_variants)


def get_conference_booktitles():
    """Return mapping of conference areas to DBLP booktitle patterns."""
    return {
        'aaai': ['AAAI', 'AAAI/IAAI'],
        'ijcai': ['IJCAI'],
        'cvpr': ['CVPR', 'CVPR (1)', 'CVPR (2)'],
        'eccv': [f'ECCV ({i})' for i in range(1, 90)],
        'iccv': ['ICCV'],
        'icml': ['ICML', 'ICML (1)', 'ICML (2)', 'ICML (3)'],
        'kdd': ['KDD'],
        'iclr': ['ICLR', 'ICLR (Poster)'],
        'nips': ['NeurIPS', 'NIPS'],
        'acl': ['ACL', 'ACL (1)', 'ACL (2)', 'ACL/IJCNLP', 'ACL/IJCNLP (1)', 'ACL/IJCNLP (2)'],
        'emnlp': ['EMNLP', 'EMNLP-CoNLL', 'EMNLP/IJCNLP (1)', 'HLT/EMNLP', 'EMNLP (1)'],
        'naacl': ['NAACL', 'NAACL-HLT', 'NAACL-HLT (1)', 'NAACL (Long Papers)', 'HLT-NAACL'],
        'sigir': ['SIGIR', 'WSDM'],
        'www': ['WWW']
    }


def parse_dblp_for_papers(data_dir: str, monash_researchers: set, ai_areas: list):
    """Parse DBLP XML to extract paper titles for Monash researchers in AI."""
    dblp_file = os.path.join(data_dir, "dblp.xml.xz")
    
    if not os.path.exists(dblp_file):
        print(f"Warning: {dblp_file} not found. Paper titles will not be available.")
        return {}
    
    print("Parsing DBLP XML for paper titles (this will take a few minutes)...")
    
    # Get conference booktitle mapping
    conf_booktitles = get_conference_booktitles()
    
    # Build reverse lookup: booktitle -> area
    booktitle_to_area = {}
    for area, booktitles in conf_booktitles.items():
        for bt in booktitles:
            booktitle_to_area[bt.lower()] = area
    
    # Paper storage: researcher_name -> list of papers
    papers = defaultdict(list)
    
    # Counter for progress
    counter = 0
    
    try:
        with lzma.open(dblp_file, 'rb') as xz:
            # Use iterparse for memory-efficient streaming
            context = ET.iterparse(xz, events=('end',))
            context = iter(context)
            event, root = next(context)
            
            for event, elem in context:
                if elem.tag not in ('inproceedings', 'article'):
                    continue
                
                counter += 1
                if counter % 50000 == 0:
                    print(f"  Processed {counter} papers...")
                
                # Get booktitle
                booktitle_elem = elem.find('booktitle')
                if booktitle_elem is None or booktitle_elem.text is None:
                    elem.clear()
                    continue
                
                booktitle = booktitle_elem.text.strip()
                booktitle_lower = booktitle.lower()
                
                # Check if this is an AI conference
                area = booktitle_to_area.get(booktitle_lower)
                if area is None:
                    # Try partial matches
                    for bt_pattern, bt_area in booktitle_to_area.items():
                        if bt_pattern in booktitle_lower or booktitle_lower in bt_pattern:
                            area = bt_area
                            break
                
                if area not in ai_areas and area not in ['aaai', 'ijcai', 'cvpr', 'eccv', 'iccv', 'icml', 'kdd', 'iclr', 'nips', 'neurips', 'acl', 'emnlp', 'naacl', 'sigir', 'www']:
                    elem.clear()
                    continue
                
                # Get authors
                author_elems = elem.findall('author')
                if not author_elems:
                    elem.clear()
                    continue
                
                author_names = []
                for author_elem in author_elems:
                    if author_elem.text:
                        author_names.append(author_elem.text.strip())
                
                # Check if any author is a Monash researcher
                matching_authors = []
                for author in author_names:
                    if author in monash_researchers:
                        matching_authors.append(author)
                
                if not matching_authors:
                    elem.clear()
                    continue
                
                # Extract paper details
                title_elem = elem.find('title')
                title = title_elem.text.strip() if title_elem is not None and title_elem.text else "N/A"
                
                year_elem = elem.find('year')
                year = int(year_elem.text) if year_elem is not None and year_elem.text else 0
                
                pages_elem = elem.find('pages')
                pages = pages_elem.text if pages_elem is not None and pages_elem.text else ""
                
                ee_elem = elem.find('ee')
                url = ee_elem.text if ee_elem is not None and ee_elem.text else ""
                
                # Create paper record
                paper = {
                    'title': title,
                    'year': year,
                    'conference': booktitle,
                    'area': area,
                    'pages': pages,
                    'url': url,
                    'authors': author_names,
                    'num_authors': len(author_names)
                }
                
                # Add to each matching author
                for author in matching_authors:
                    papers[author].append(paper)
                
                # Clear element to free memory
                elem.clear()
                
    except Exception as e:
        print(f"Error parsing DBLP: {e}")
    
    print(f"Processed {counter} total papers, found {sum(len(p) for p in papers.values())} papers for Monash AI researchers")
    
    return dict(papers)


def find_monash_ai_researchers(data_dir: str):
    """Find all Monash University researchers in AI."""
    print("Loading faculty data...")
    faculty = load_faculty_data(data_dir)
    
    print("Loading ORCID data...")
    orcid_map = load_orcid_data(data_dir)
    
    print("Loading aliases...")
    aliases = load_aliases(data_dir)
    
    print("Loading institutions...")
    institutions = load_institutions(data_dir)
    
    print("Loading publications (this may take a moment)...")
    publications = load_publications(data_dir)
    
    ai_areas, all_ai_areas, conf_to_area = get_ai_areas()
    
    # Find Monash researchers
    print("Finding Monash researchers...")
    monash_researchers = {}
    monash_names = set()
    
    for name, info in faculty.items():
        if is_monash_affiliation(info['affiliation']):
            monash_researchers[name] = {
                'info': info,
                'orcid': orcid_map.get(name, info['orcid']),
                'publications': [],
                'ai_areas': set(),
                'total_papers': 0,
                'total_adjusted': 0.0,
                'year_range': [None, None],
                'paper_titles': []  # Will be populated from DBLP
            }
            monash_names.add(name)
    
    # Also check aliases
    for alias, canonical in aliases.items():
        if canonical in monash_researchers and alias in faculty:
            # Merge alias info if needed
            pass
    
    # Process publications from generated-author-info.csv
    print("Processing publication statistics...")
    for pub in publications:
        name = pub['name']
        area = pub['area']
        
        # Check if this is a Monash researcher
        if name in monash_researchers and area in all_ai_areas:
            researcher = monash_researchers[name]
            researcher['publications'].append(pub)
            researcher['ai_areas'].add(area)
            researcher['total_papers'] += pub['count']
            researcher['total_adjusted'] += pub['adjusted_count']
            
            # Update year range
            year = pub['year']
            if researcher['year_range'][0] is None or year < researcher['year_range'][0]:
                researcher['year_range'][0] = year
            if researcher['year_range'][1] is None or year > researcher['year_range'][1]:
                researcher['year_range'][1] = year
    
    # Filter to only those with AI publications
    ai_researchers = {
        name: data for name, data in monash_researchers.items()
        if data['ai_areas']
    }
    
    # Now parse DBLP for paper titles
    if ai_researchers:
        ai_researcher_names = set(ai_researchers.keys())
        paper_titles = parse_dblp_for_papers(data_dir, ai_researcher_names, all_ai_areas)
        
        # Add paper titles to researchers
        for name, researcher in ai_researchers.items():
            if name in paper_titles:
                researcher['paper_titles'] = paper_titles[name]
            else:
                researcher['paper_titles'] = []
    
    return ai_researchers, ai_areas, institutions, conf_to_area


def get_area_display_name(area: str) -> str:
    """Get human-readable name for an area."""
    area_names = {
        'ai': 'AI (General)',
        'aaai': 'AAAI',
        'ijcai': 'IJCAI',
        'vision': 'Computer Vision',
        'cvpr': 'CVPR',
        'eccv': 'ECCV',
        'iccv': 'ICCV',
        'mlmining': 'Machine Learning & Data Mining',
        'icml': 'ICML',
        'kdd': 'KDD',
        'iclr': 'ICLR',
        'nips': 'NeurIPS',
        'neurips': 'NeurIPS',
        'nlp': 'Natural Language Processing',
        'acl': 'ACL',
        'emnlp': 'EMNLP',
        'naacl': 'NAACL',
        'inforet': 'Web & Information Retrieval',
        'sigir': 'SIGIR',
        'www': 'WWW'
    }
    return area_names.get(area, area)


def escape_for_logseq(text: str) -> str:
    """Escape special characters for Logseq."""
    # Replace square brackets for Logseq links
    text = text.replace('[[', '[[').replace(']]', ']]')
    return text


def generate_simple_report(researchers: dict, ai_areas: dict, institutions: dict, conf_to_area: dict, output_file: str):
    """Generate a simple markdown report without HTML tags or collapsible sections."""
    
    with open(output_file, 'w', encoding='utf-8') as f:
        # Simple markdown header
        f.write("# Monash University AI Researchers\n\n")
        f.write("Report of Monash University researchers in Artificial Intelligence fields based on CSRankings data, including their paper titles from DBLP.\n\n")
        
        # Summary
        f.write("## Summary\n\n")
        total_researchers = len(researchers)
        total_papers = sum(len(r['paper_titles']) for r in researchers.values())
        f.write(f"- **Total AI Researchers**: {total_researchers}\n")
        f.write(f"- **Total AI Papers with Titles**: {total_papers}\n")
        f.write(f"- **Data Source**: CSRankings (csrankings.org) + DBLP\n")
        f.write(f"- **Generated**: April 2026\n\n")
        
        # AI Areas covered
        f.write("## AI Research Areas Covered\n\n")
        for category, areas in ai_areas.items():
            area_names = [get_area_display_name(a) for a in areas]
            f.write(f"- **{category.capitalize()}**: {', '.join(area_names)}\n")
        f.write("\n")
        
        # Sort researchers by adjusted count (descending)
        sorted_researchers = sorted(
            researchers.items(),
            key=lambda x: x[1]['total_adjusted'],
            reverse=True
        )
        
        # Individual researcher profiles
        f.write("## Researchers (by adjusted publication count)\n\n")
        f.write("Researchers are listed in order of total adjusted publication count.\n\n")
        
        for idx, (name, data) in enumerate(sorted_researchers, 1):
            info = data['info']
            orcid = data['orcid']
            
            # Clean name for display
            clean_name = name.replace(' 0001', '').replace(' 0002', '').replace(' 0003', '')
            
            # Researcher section
            f.write(f"### {idx}. {clean_name}\n\n")
            
            # Basic info as bullet list
            f.write(f"- **Full Name**: {name}\n")
            f.write(f"- **Institution**: {info['affiliation']}\n")
            if info['homepage']:
                f.write(f"- **Homepage**: {info['homepage']}\n")
            if info['scholar_id']:
                f.write(f"- **Google Scholar**: https://scholar.google.com/citations?user={info['scholar_id']}\n")
            if orcid:
                f.write(f"- **ORCID**: https://orcid.org/{orcid}\n")
            
            # Institution details
            inst_name = info['affiliation']
            if inst_name in institutions:
                inst = institutions[inst_name]
                f.write(f"- **Region**: {inst['region']} ({inst['country'].upper()})\n")
            
            # Publication statistics
            f.write(f"- **Total Papers**: {data['total_papers']:.0f}\n")
            f.write(f"- **Adjusted Count**: {data['total_adjusted']:.2f}\n")
            f.write(f"- **Active Years**: {data['year_range'][0]} - {data['year_range'][1]}\n")
            f.write(f"- **AI Areas**: {len(data['ai_areas'])}\n")
            f.write(f"- **Papers with Titles**: {len(data['paper_titles'])}\n")
            
            # Tags for researcher
            tags = []
            for area in data['ai_areas']:
                tags.append(f"#{area}")
            if tags:
                f.write(f"- **Tags**: {' '.join(tags)}\n")
            
            f.write("\n")
            
            # AI Areas breakdown
            f.write("#### AI Research Areas\n\n")
            sorted_areas = sorted(data['ai_areas'], key=lambda a: get_area_display_name(a))
            for area in sorted_areas:
                # Count papers in this area
                area_pubs = [p for p in data['publications'] if p['area'] == area]
                total_count = sum(p['count'] for p in area_pubs)
                total_adj = sum(p['adjusted_count'] for p in area_pubs)
                year_range = f"{min(p['year'] for p in area_pubs)}-{max(p['year'] for p in area_pubs)}"
                
                f.write(f"- **{get_area_display_name(area)}**: {total_count:.0f} papers ")
                f.write(f"(adjusted: {total_adj:.2f}), {year_range}\n")
            f.write("\n")
            
            # Paper Titles Section - flat list by year
            f.write("#### Paper Titles\n\n")
            
            if data['paper_titles']:
                # Group papers by year
                year_papers = defaultdict(list)
                for paper in data['paper_titles']:
                    year_papers[paper['year']].append(paper)
                
                for year in sorted(year_papers.keys(), reverse=True):
                    papers_in_year = year_papers[year]
                    f.write(f"**{year}** ({len(papers_in_year)} papers):\n\n")
                    
                    for i, paper in enumerate(papers_in_year, 1):
                        title = paper['title']
                        # Clean up title
                        title = title.replace('\n', ' ').replace('\r', ' ')
                        
                        # Only paper title, nothing else
                        f.write(f"{i}. {title}\n")
                    
                    f.write("\n")
            else:
                f.write("*No paper titles available in DBLP data for this researcher.*\n")
            
            f.write("---\n\n")
        
        # Appendices
        f.write("## Appendix A: Methodology\n\n")
        f.write("This report was generated by:\n\n")
        f.write("1. Loading faculty data from all `csrankings-*.csv` files\n")
        f.write("2. Identifying researchers with 'Monash University' affiliations\n")
        f.write("3. Loading publication data from `generated-author-info.csv`\n")
        f.write("4. Filtering for AI research areas (ai, vision, mlmining, nlp, inforet)\n")
        f.write("5. Parsing `dblp.xml.xz` to extract paper titles for AI conferences\n")
        f.write("6. Matching papers to Monash researchers by author name\n")
        f.write("7. Aggregating statistics and generating this report\n\n")
        
        f.write("## Appendix B: Data Files Used\n\n")
        f.write("| File | Description |\n")
        f.write("|------|-------------|\n")
        f.write("| `csrankings-[a-z].csv` | Faculty information (name, affiliation, homepage, scholar ID, ORCID) |\n")
        f.write("| `generated-author-info.csv` | Publication statistics (author, dept, area, count, adjusted count, year) |\n")
        f.write("| `dblp.xml.xz` | DBLP XML database with paper titles, authors, and venues |\n")
        f.write("| `orcid.csv` | ORCID identifier mappings |\n")
        f.write("| `dblp-aliases.csv` | Name alias mappings for author disambiguation |\n")
        f.write("| `institutions.csv` | Institution metadata (region, country, homepage) |\n\n")
        
        f.write("## Appendix C: AI Area Definitions\n\n")
        f.write("AI areas are defined in CSRankings as follows:\n\n")
        for category, areas in ai_areas.items():
            confs = [a for a in areas if a != category]
            f.write(f"- **{category}**: {', '.join(confs)}\n")
        f.write("\n")
        
        f.write("---\n\n")
        f.write("**Tags**: #monash-university #ai-research #csrankings #computer-science #australia #academic-research\n\n")
        f.write("*Report generated from CSRankings and DBLP data. Last updated: April 2026*\n")
    
    print(f"\nReport saved to: {output_file}")


def main():
    """Main function."""
    # Get the script's directory
    script_dir = Path(__file__).parent.absolute()
    
    # Data directory is the parent of script directory (or same directory if script is in root)
    data_dir = script_dir
    
    output_file = "monash_ai_researchers.md"
    
    print("=" * 60)
    print("Monash University AI Researchers Report Generator")
    print("(Simple Markdown)")
    print("=" * 60)
    print()
    
    # Find researchers
    researchers, ai_areas, institutions, conf_to_area = find_monash_ai_researchers(str(data_dir))
    
    print(f"\nFound {len(researchers)} Monash AI researchers")
    
    # Generate report
    generate_simple_report(researchers, ai_areas, institutions, conf_to_area, output_file)
    
    print(f"\nDone! Report written to: {output_file}")
    print(f"\nTop researchers by adjusted publication count:")
    
    sorted_researchers = sorted(researchers.items(), key=lambda x: x[1]['total_adjusted'], reverse=True)
    for idx, (name, data) in enumerate(sorted_researchers[:10], 1):
        paper_count = len(data['paper_titles'])
        print(f"  {idx}. {name}: {data['total_adjusted']:.2f} adjusted count, {paper_count} papers with titles")


if __name__ == "__main__":
    main()
