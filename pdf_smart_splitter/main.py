import sys
import os
import io
import json
import html 
import requests
import pandas as pd

from dotenv import load_dotenv

from azure.ai.documentintelligence import DocumentIntelligenceClient
from azure.ai.documentintelligence.models import AnalyzeDocumentRequest, ContentFormat, AnalyzeResult
from azure.core.credentials import AzureKeyCredential


class PDFSmartSplitter:
    def __init__(self, env_filename,pdf_filename=None, pdf_url=None,verbose=0):
        load_dotenv(env_filename)
        self.pdf_filename = pdf_filename
        self.pdf_url = pdf_url
        self.verbose = verbose
    
    def run(self,save_path = None):
        try:
            self.read_pdf()
        except Exception as e:
            print(f"Error reading pdf: {e}")
            return None
        try:
            self.build_sections_parent_hierarchy()
        except Exception as e:
            print(f"Error building sections parent hierarchy: {e}")
            return None

        try:
            self.split_doc_into_sections()
        except Exception as e:
            print(f"Error splitting document into sections: {e}")
            return None

        try:
            self.prepare_doc_paragraphs()
        except Exception as e:
            print(f"Error preparing document paragraphs: {e}")
            return None

        try:
            self.prepare_doc_tables()
        except Exception as e:
            print(f"Error preparing document tables: {e}")
            return None

        try:
            self.merge_document_content()
        except Exception as e:
            print(f"Error merging document content: {e}")
            return None

        if save_path:
            save_pdf_path = "output"
            if self.pdf_url:
                save_pdf_path = self.pdf_url.split("/")[-1]
            elif self.pdf_filename:
                save_pdf_path = self.pdf_filename.split("/")[-1]
            
            if not os.path.exists(os.path.join(save_path,save_pdf_path)):
                os.makedirs(os.path.join(save_path,save_pdf_path))

            for i, s in self.df_doc_sections_merge.iterrows():
                if len(s.merge_content)>0:
                    with open(os.path.join(save_path,save_pdf_path,f"section_{s.section}_level_{s.level}.txt"), "w") as f:
                        f.write(s.merge_content)

        return self.merge_document_content()

    def read_pdf(self):
        """Reads a PDF document using Azure Form Recognizer and returns the analysis result in markdown format.

        Returns:
            AnalyzeResult: The result of the document analysis object, or None if no PDF file or URL is provided.
        """
        # Get Azure Credentials
        document_intelligence_creds = AzureKeyCredential(os.getenv("AZURE_FORM_RECOGNIZER_KEY"))

        # Document Intelligence Output to markdown format
        document_intelligence_client = DocumentIntelligenceClient(endpoint=os.getenv("AZURE_FORM_RECOGNIZER_ENDPOINT"), 
                                                                    credential=document_intelligence_creds)
        if self.pdf_url:             
            poller = document_intelligence_client.begin_analyze_document(
            "prebuilt-layout",
            AnalyzeDocumentRequest(url_source=self.pdf_url),
            output_content_format=ContentFormat.MARKDOWN,
            )
        elif self.pdf_filename:
            with open(self.pdf_filename, "rb") as f:
                    poller = document_intelligence_client.begin_analyze_document(
                    "prebuilt-layout",
                    #AnalyzeDocumentRequest(url_source=filename),
                    AnalyzeDocumentRequest(bytes_source=f.read()),        
                    output_content_format=ContentFormat.MARKDOWN,
                )
        else:
            print("No pdf file or url provided")
            return None
        
        self.result_mkd: AnalyzeResult = poller.result()

        if self.verbose>0:
            print(f"pages:{len(self.result_mkd.pages)}")
            print(f"tables:{len(self.result_mkd.tables)}")
            print(f"sections:{len(self.result_mkd.sections)}")
            print(f"paragraphs:{len(self.result_mkd.paragraphs)}")
        
        return self.result_mkd
    
    def build_sections_parent_hierarchy(self):
        """
        Builds a DataFrame representing the hierarchy of sections and their parent-child relationships.
        This method processes the sections in the `self.result_mkd.sections` attribute and constructs a DataFrame with columns:
        - "section": The section identifier.
        - "parent": The parent section identifier.
        - "level": The hierarchical level of the section.
        The hierarchy is determined based on the nested structure of elements within each section.
        
        Returns:
            pd.DataFrame: A DataFrame containing the hierarchy of sections with their respective parent and level information.
        """
        self.df_doc_parent_sections = pd.DataFrame(columns=["section","parent","level"])
        parent_level={0:0}
        level = 0
        stop=0
        for id,s in enumerate(self.result_mkd.sections):
            s_dict=s.as_dict()
            for e in s_dict["elements"]:
                if "sections" in e:            
                    try:
                        level = parent_level[id]+1                
                    except:
                        parent_id=int(self.df_doc_parent_sections[self.df_doc_parent_sections.section==str(id)].parent)
                        level=parent_level[parent_id]+1
                        parent_level[id]=level
                        #parent_level[e.split("/")[-1]]=level+1
                        level = parent_level[id]+1 
                        pass

                    self.df_doc_parent_sections = pd.concat([self.df_doc_parent_sections, pd.DataFrame([{"section":e.split("/")[-1],"parent":id,"level":level}])], ignore_index=True)
            
        
        self.df_doc_parent_sections["section"] = self.df_doc_parent_sections["section"].astype(int)
        self.df_doc_parent_sections["parent"] = self.df_doc_parent_sections["parent"].astype(str)
        self.df_doc_parent_sections["level"] = self.df_doc_parent_sections["level"].fillna(0).astype(str)

        return self.df_doc_parent_sections
    
    def split_doc_into_sections(self):
        doc_sections=[]
        temp = None

        for id,s in enumerate(self.result_mkd.sections):
            s_dict=s.as_dict()
            if temp and s_dict.get("spans")[0].get("offset")<temp.get("section_max"):
                level+=1
            else:
                level=0
            
            temp = {"section":id,
                    "elements": s_dict.get("elements"), 
                    "offset": s_dict.get("spans")[0].get("offset"), 
                    "length": s_dict.get("spans")[0].get("length"),
                    "section_max": s_dict.get("spans")[0].get("length") +s_dict.get("spans")[0].get("offset")
                    } 
                
            doc_sections.append(temp)

        df_doc_sections = pd.DataFrame(doc_sections)
        df_doc_sections["section"] = df_doc_sections["section"].astype(int)

        self.df_doc_sections_merge = pd.merge(self.df_doc_parent_sections,df_doc_sections,left_on="section",right_on="section",how="outer",indicator=False)
        self.df_doc_sections_merge["level"] = self.df_doc_sections_merge["level"].fillna(0).astype(int)

        # Split elements into separate columns for lists of paragraphs, sections, tables, figures and others
        self.df_doc_sections_merge["sections"] = self.df_doc_sections_merge["elements"].apply(lambda x: [int(p.split("/")[-1]) for p in x if "sections" in p])
        self.df_doc_sections_merge["paragraphs"] = self.df_doc_sections_merge["elements"].apply(lambda x: [int(p.split("/")[-1]) for p in x if "paragraphs" in p])
        self.df_doc_sections_merge["tables"] = self.df_doc_sections_merge["elements"].apply(lambda x: [int(p.split("/")[-1]) for p in x if "tables" in p])
        self.df_doc_sections_merge["figures"] = self.df_doc_sections_merge["elements"].apply(lambda x: [int(p.split("/")[-1]) for p in x if "figures" in p])
        self.df_doc_sections_merge["others"] = self.df_doc_sections_merge["elements"].apply(lambda x: [p for p in x if "sections" not in p and "paragraphs" not in p and "tables" not in p and "figures" not in p])

        return self.df_doc_sections_merge
    

    def prepare_doc_paragraphs(self):
        """
        Prepares a DataFrame of document paragraphs with their respective sections.

        Returns:
            pd.DataFrame: A DataFrame containing the paragraphs with their section information.
        """
        doc_paragraphs = []

        for i, p in enumerate(self.result_mkd.paragraphs):
            p_dict = p.as_dict()
            temp = {
                "id": i + 1,
                "section": None,
                "content": p_dict.get("content"),
                "role": p_dict.get("role"),
                "pageNumber": p_dict.get("boundingRegions")[0].get("pageNumber"),
                "offset": p_dict.get("spans")[0].get("offset"),
                "length": p_dict.get("spans")[0].get("length"),
            }
            doc_paragraphs.append(temp)

        self.df_doc_paragraphs = pd.DataFrame(doc_paragraphs)
        self.df_doc_paragraphs.set_index("id", inplace=True)

        # Merge sections and paragraphs
        for i, s in self.df_doc_sections_merge.iterrows():
            for p in s.elements:
                if "paragraphs" in p:
                    try:
                        self.df_doc_paragraphs.loc[int(p.split("/")[-1]), ["section"]] = s.section
                    except KeyError:
                        pass

        return self.df_doc_paragraphs
    

    def table_to_html(self,table):
        table_html = "<table>"
        rows = [
            sorted([cell for cell in table.cells if cell.row_index == i], key=lambda cell: cell.column_index)
            for i in range(table.row_count)
        ]
        for row_cells in rows:
            table_html += "<tr>"
            for cell in row_cells:
                tag = "th" if (cell.kind == "columnHeader" or cell.kind == "rowHeader") else "td"
                cell_spans = ""
                #if cell.column_span > 1:
                #    cell_spans += f" colSpan={cell.column_span}"
                #if cell.row_span > 1:
                #    cell_spans += f" rowSpan={cell.row_span}"
                #table_html += f"<{tag}{cell_spans}>{html.escape(cell.content)}</{tag}>"
                table_html += f"<{tag}>{html.escape(cell.content)}</{tag}>"
            table_html += "</tr>"
        table_html += "</table>"
        return table_html

    def prepare_doc_tables(self):
        """
        Prepares a DataFrame of document tables with their respective sections.

        Returns:
            pd.DataFrame: A DataFrame containing the tables with their section information.
        """
        doc_tables = []

        for i, t in enumerate(self.result_mkd.tables):
            t_dict = t.as_dict()
            temp = {
                "id": i,
                "section": None,
                "table_html": self.table_to_html(t),
                "pageNumber_start": t_dict.get("cells")[0].get("boundingRegions")[0].get("pageNumber"),
                "pageNumber_end": t_dict.get("cells")[-1].get("boundingRegions")[-1].get("pageNumber"),
            }
            doc_tables.append(temp)

        self.df_doc_tables = pd.DataFrame(doc_tables)
        self.df_doc_tables.set_index("id", inplace=True)

        # Merge sections and tables
        for i, s in self.df_doc_sections_merge.iterrows():
            for p in s.elements:
                if "tables" in p:
                    try:
                        self.df_doc_tables.loc[int(p.split("/")[-1]), ["section"]] = s.section
                    except KeyError:
                        pass

        return self.df_doc_tables
    
    def get_section_merged_content(self,c,skip_subsections=False):
        result = ""
        try:
            for j, l in enumerate(c.elements):
                    if "sections" in l and skip_subsections==False:            
                        result = result + "\n" + (self.get_section_merged_content(self.df_doc_sections_merge.iloc[int(l.split("/")[-1])]))
                    if "paragraphs" in l:
                        result = result + "\n" + self.df_doc_paragraphs.loc[int(l.split("/")[-1])].content
                    elif "tables" in l:
                        result = result + "\n" + self.df_doc_tables.loc[int(l.split("/")[-1])].table_html    
        except:
            print(l)
            raise
        return result

    def merge_document_content(self,skip_level=0):
        """
        Merges the content of the document sections, paragraphs, and tables into a single string for each section.

        Returns:
            pd.DataFrame: A DataFrame with the merged content for each section.
        """
        
        self.df_doc_sections_merge["section_content"] = ""
        self.df_doc_sections_merge["section_all_content"] = ""

        for i, c in self.df_doc_sections_merge.iterrows():
            if int(c.level) > skip_level:
                self.df_doc_sections_merge.loc[i, "section_content"] = self.get_section_merged_content(c,skip_subsections=True)
                self.df_doc_sections_merge.loc[i, "section_all_content"] = self.get_section_merged_content(c,skip_subsections=False)

        # Add merged content length
        self.df_doc_sections_merge["content_len"] = self.df_doc_sections_merge["section_content"].fillna("").apply(lambda x: len(x))
        self.df_doc_sections_merge["all_content_len"] = self.df_doc_sections_merge["section_all_content"].fillna("").apply(lambda x: len(x))

        return self.df_doc_sections_merge

    def chunk_documnent(self,max_chunk_len = 2500,chunk_overlap = 500):
        self.df_doc_sections_merge["is_chunk"] = None
        self.df_doc_sections_merge["chunk"] = None

        def turnoff_sub_sections_chunking(df):
            for i, row in df.iterrows():
                for s in row.sections:
                    self.df_doc_sections_merge.loc[self.df_doc_sections_merge.section==s,["is_chunk"]] =False

        def resolve_parent_section_chunking(df,l):
            for p in df.parent.drop_duplicates(): 
                if len(self.df_doc_sections_merge[(self.df_doc_sections_merge.parent==p) & (self.df_doc_sections_merge.is_chunk.isnull())])==0:
                    self.df_doc_sections_merge.loc[(self.df_doc_sections_merge.section==p),["is_chunk"]] =False

        def split_content_to_chunks(content,chunk_max_len,chunk_overlap):
            import json
            
            content_list = content.split("\n")
            temp = ""
            chunks=[]
            for c in content_list:
                temp=temp +" " + c
                if len(temp)>chunk_max_len:
                    chunks.append(temp)
                    temp=" "
            if len(temp)>0:
                    chunks.append(temp)
                    
            return json.dumps(chunks)

        self.df_doc_sections_merge.loc[(self.df_doc_sections_merge.all_content_len<1),"is_chunk"] = False

                
        for l in self.df_doc_sections_merge.level.drop_duplicates(): 
            # STEP 1: if level l section with all_content_len<max_chunk_len then tag the whole content as one chunk
            self.df_doc_sections_merge.loc[(self.df_doc_sections_merge.level==l) 
                    & (self.df_doc_sections_merge.all_content_len<max_chunk_len) 
                    & (self.df_doc_sections_merge.is_chunk.isnull()),["chunks"]] = self.df_doc_sections_merge[(self.df_doc_sections_merge.level==l) 
                                                                & (self.df_doc_sections_merge.all_content_len<max_chunk_len) 
                                                                & (self.df_doc_sections_merge.is_chunk.isnull())].section_all_content.apply(lambda x:json.dumps([x]))
            self.df_doc_sections_merge.loc[(self.df_doc_sections_merge.level==l) 
                    & (self.df_doc_sections_merge.all_content_len<max_chunk_len) 
                    & (self.df_doc_sections_merge.is_chunk.isnull()),["is_chunk"]] =True
                    
            # turnoff sub-sections from chunking for sections with all_content_len<max_chunk_len
            turnoff_sub_sections_chunking(self.df_doc_sections_merge[(self.df_doc_sections_merge.level==l) & (self.df_doc_sections_merge.all_content_len<max_chunk_len) & (self.df_doc_sections_merge.is_chunk==True)])

            #  STEP 2: Chunk remaining sections
            # 2.1: Add section level content as chunk if it is less than max_chunk_len
            self.df_doc_sections_merge.loc[(self.df_doc_sections_merge.level==l) 
                    & (self.df_doc_sections_merge.content_len<max_chunk_len)
                    & (self.df_doc_sections_merge.is_chunk.isnull()),["chunks"]] = self.df_doc_sections_merge[(self.df_doc_sections_merge.level==l) 
                                                                & (self.df_doc_sections_merge.content_len<max_chunk_len)
                                                                & (self.df_doc_sections_merge.is_chunk.isnull())].section_content.apply(lambda x:json.dumps([x]))
            
            # 2.2: If content_len is less than max_chunk_len then tag the section content as one chunk
            self.df_doc_sections_merge.loc[(self.df_doc_sections_merge.level==l) 
                    & (self.df_doc_sections_merge.content_len<max_chunk_len) 
                    & (self.df_doc_sections_merge.is_chunk.isnull()),["is_chunk"]] =True
            
            # 2.3: If not, split the content into chunks
            self.df_doc_sections_merge.loc[(self.df_doc_sections_merge.level==l) 
                    & (self.df_doc_sections_merge.content_len>max_chunk_len) 
                    & (self.df_doc_sections_merge.is_chunk.isnull()),["chunks"]] = self.df_doc_sections_merge[(self.df_doc_sections_merge.level==l) 
                                                                    & (self.df_doc_sections_merge.content_len>max_chunk_len) 
                                                                    & (self.df_doc_sections_merge.is_chunk.isnull())].section_content.apply(lambda x:split_content_to_chunks(x,max_chunk_len,chunk_overlap))
            # 2.4: Split chunk content if content_len>max_chunk_len
            
            # 2.5: Tag splitted chunks are completed (is_chunk=True)
            self.df_doc_sections_merge.loc[(self.df_doc_sections_merge.level==l) 
                    & (self.df_doc_sections_merge.content_len>max_chunk_len) 
                    & (self.df_doc_sections_merge.is_chunk.isnull()),["is_chunk"]] =True


            # Turnoff parent section from chunking if all sub-sections are chunked
            #resolve_parent_section_chunking(self.df_doc_sections_merge[(self.df_doc_sections_merge.level==l)],l)

        # Update all sections with all_content_len>max_chunk_len and is_chunkis None to is_chunk=False
        #self.df_doc_sections_merge.loc[(self.df_doc_sections_merge.all_content_len>max_chunk_len) & (self.df_doc_sections_merge.is_chunk.isnull()),["is_chunk"]] =False

        if self.verbose>0:
            print(f"chunk_is_null count:{len(self.df_doc_sections_merge[(self.df_doc_sections_merge.is_chunk.isnull())])}")
            print(f"chunk_is_true count:{len(self.df_doc_sections_merge[(self.df_doc_sections_merge.is_chunk==True)])}")
            print(f"chunk_is_false count:{len(self.df_doc_sections_merge[(self.df_doc_sections_merge.is_chunk==False)])}")

        def count_chunks(chunks):
            try:
                if chunks is None:
                    return 0
                return len(json.loads(chunks))
            except:
                return 0
        def len_max_chunks(chunks):
            try:
                if chunks is None:
                    return 0
                max=0
                for c in json.loads(chunks):
                    if len(c)>max:
                        max=len(c)
                return max
            except:
                return 0
            
        def len_chunks(chunks):
            try:
                if chunks is None:
                    return 0
                
                return [len(c)for c in json.loads(chunks)]
            except:
                return 0
            
        self.df_doc_sections_merge["chunks_count"] = self.df_doc_sections_merge.chunks.apply(lambda x:count_chunks(x))
        self.df_doc_sections_merge["chunks_max_len"] = self.df_doc_sections_merge.chunks.apply(lambda x:len_max_chunks(x))
        self.df_doc_sections_merge["chunks_len"] = self.df_doc_sections_merge.chunks.apply(lambda x:len_chunks(x))

        return self.df_doc_sections_merge
