def process_pdf_auto(self,
                        filename: str,
                        filecontent=None,
                        direction="dataframe",
                        save_text_coordinates_to_local: bool = False,
                        save_file_to_local: bool = False,
                        extract_by_page: bool = True):

    try:
        pdf_reader = PDFReader(
            file_path=os.path.join(self.current_app_config.input_path, filename),
            output_path=self.current_app_config.output_path,
            extract_images=self.current_app_config.extract_images,
            s3_client=self.s3_client
        )
        if filecontent:
            data_coordinates, doc_total_pages = pdf_reader.read_pdf_file(filecontent=filecontent)
        else:
            data_coordinates, doc_total_pages = pdf_reader.read_pdf_file()


        # SAVE data coordinates is useful to investigate a problem or understand how data is structured within a document
        if save_text_coordinates_to_local:
            data_coordinates_filename = f'data_coordinates_{filename.split(".")[0]}_{str(datetime.date.today())}.csv'
            pd.DataFrame(data_coordinates).to_csv(
                os.path.join(self.current_app_config.output_path, data_coordinates_filename)
            )

        df_pdf_data = pd.DataFrame(data_coordinates)



        # Extract data as tables
        if direction=="dataframe":
            procesed_file_content = self.extract_auto_tables(df_pdf_data=df_pdf_data,
                                                                filename=filename,
                                                                extract_by_page=extract_by_page)
        # Extract data as key/value
        else:
            procesed_file_content = self.extract_auto_keyvalues(df_pdf_data=df_pdf_data,
                                                                filename=filename,
                                                                extract_by_page=extract_by_page)
        if save_file_to_local:
            json_filename = F"{filename.split('.')[0]}.json"
            with open(os.path.join(self.current_app_config.output_path, json_filename), "w") as f:
                json.dump(procesed_file_content, f)

        return procesed_file_content
    except Exception as e:
        logger.info(
            f"Error occurred during process_pdf_auto(filename={filename})"
        )
        logger.info(e)
        return None

def extract_auto_keyvalues(self, df_pdf_data, filename, max_treshold:int = 3, extract_by_page: bool = True):

    """
    :param df_pdf_data:
    :param filename:
    :param extract_by_page:
    :return:
    """


    max_pages = set(df_pdf_data.page_num)

    new_res = pd.DataFrame(columns=['page_num', 'text', 'bbox.x0', 'bbox.y0', 'bbox.x1', 'bbox.y1',
                                    'fontname', 'fontsize'
                                    ]
                            )
    for current_page in max_pages:
        temp_string = ""
        fontname_list = []
        fontsize_list = []
        res_list = df_pdf_data[df_pdf_data.page_num == current_page]
        res_list = res_list.sort_values(by=["bbox.y0", "bbox.x0"], ascending=[False, True], axis=0)

        res_list["prev_bbox.y0"] = res_list["bbox.y0"].shift()
        res_list["prev_bbox.x0"] = res_list["bbox.x0"].shift()
        res_list["prev_fontname"] = res_list["fontname"].shift()
        res_list["prev_fontsize"] = res_list["fontsize"].shift()
        res_list["diff_bbox.x0"] = res_list["bbox.x0"] - res_list["prev_bbox.x0"]
        res_list["diff_bbox.x0"] = res_list.apply(
            lambda x: 1000 if x["bbox.y0"] != x["prev_bbox.y0"] else x["diff_bbox.x0"], axis=1)
        res_list["ratio_fontsize_diff_x0"] = res_list["diff_bbox.x0"] / res_list["fontsize"]

        for i0, (_, r) in enumerate(res_list.iterrows()):
            # Clean text
            temp_text = r["text"].replace(u'\xa0', u' ')

            # Check if is same content
            if r["fontname"] == r["prev_fontname"] and r["fontsize"] == r["prev_fontsize"] and (
                    np.isnan(r["ratio_fontsize_diff_x0"]) == True or r["ratio_fontsize_diff_x0"] < max_treshold):
                temp_string += temp_text
                if temp_string == "":
                    page_num = r["page_num"]
                    bbox_x0 = r["bbox.x0"]
                    bbox_y0 = r["bbox.y0"]

                if temp_text != "":
                    fontname_list.append(r['fontname'])
                    fontsize_list.append(r['fontsize'])

                bbox_x1 = r["bbox.x1"]
                bbox_y1 = r["bbox.y1"]

            elif temp_string != "":
                fontname = max(set(fontname_list), key=fontname_list.count)
                fontsize = max(set(fontsize_list), key=fontsize_list.count)

                new_res = new_res.append({"page_num": page_num,
                                            "text": temp_string.strip(),
                                            "bbox.x0": bbox_x0,
                                            "bbox.y0": bbox_y0,
                                            "bbox.x1": bbox_x1,
                                            "bbox.y1": bbox_y1,
                                            "fontname": fontname,
                                            "fontsize": fontsize, }, ignore_index=True)

                temp_string = temp_text
                page_num = r["page_num"]
                bbox_x0 = r["bbox.x0"]
                bbox_y0 = r["bbox.y0"]
                fontname_list = []
                fontsize_list = []
                if temp_text != "":
                    fontname_list.append(r['fontname'])
                    fontsize_list.append(r['fontsize'])
                bbox_x1 = r["bbox.x1"]
                bbox_y1 = r["bbox.y1"]
            else:
                temp_string = temp_text
                page_num = r["page_num"]
                bbox_x0 = r["bbox.x0"]
                bbox_y0 = r["bbox.y0"]
                if temp_text != "":
                    fontname_list.append(r['fontname'])
                    fontsize_list.append(r['fontsize'])
                bbox_x1 = r["bbox.x1"]
                bbox_y1 = r["bbox.y1"]

            # Add last row
            if temp_string != "" and i0 == (len(res_list) - 1):
                fontname = max(set(fontname_list), key=fontname_list.count)
                fontsize = max(set(fontsize_list), key=fontsize_list.count)

                new_res = new_res.append({"page_num": page_num,
                                            "text": temp_string.strip(),
                                            "bbox.x0": bbox_x0,
                                            "bbox.y0": bbox_y0,
                                            "bbox.x1": bbox_x1,
                                            "bbox.y1": bbox_y1,
                                            "fontname": fontname,
                                            "fontsize": fontsize, }, ignore_index=True)

    page_list = []
    new_res = new_res.fillna("")
    for page_id in max_pages:
        key = None
        value = None
        fontname=None
        fontsize=None
        is_used = 0
        unused = []
        separator = ":"
        row_list = []
        row_data = []
        current_bbox_y0 = None
        prev_bbox_y0 = None
        row_id = 1

        for i0, (r_id, row) in enumerate(new_res[new_res.page_num == page_id].iterrows()):
            is_used = 0
            current_bbox_y0 = row["bbox.y0"]
            # Apprend row data to row list
            # print(F"test:{row.text},prev_y0:{prev_bbox_y0}, curr_y0:{current_bbox_y0}")
            if row_data and prev_bbox_y0 and current_bbox_y0 != prev_bbox_y0:
                if key:
                    row_data.append({key: "","fontname":fontname,"fontsize":fontsize})
                row_list.append({"row_id": row_id, "row_data": row_data})
                row_data = []
                row_id += 1
            prev_bbox_y0 = current_bbox_y0

            if row.text.find(separator) >= 0 and row.fontname.find("Bold") >= 0 and row.text != "":
                key = row.text
                fontname = row.fontname
                fontsize = row.fontsize
                is_used = 1
            elif key:
                value = row.text
                fontname = row.fontname
                fontsize = row.fontsize
                is_used = 1

            if is_used == 0 and row.text != "":
                if key:
                    row_data.append({"text": key,"fontname":fontname,"fontsize":fontsize})
                row_data.append({"text": row.text,"fontname":row.fontname,"fontsize":row.fontsize})
                key = None
                value = None
                fontname = None
                fontsize = None

            # Append key:value to row_data
            if key and (value or value == ""):
                row_data.append({key: value,"fontname":fontname,"fontsize":fontsize})
                key = None
                value = None
                fontname = None
                fontsize = None

        if (prev_bbox_y0 and current_bbox_y0 != prev_bbox_y0) or i0 == (len(new_res) - 1):
            if key:
                row_data.append({key: "","fontname":fontname,"fontsize":fontsize})
            if row_data:
                row_list.append({"row_id": row_id, "row_data": row_data})
            row_data = []
            row_id += 1

        # Append row_list to page data
        page_list.append({"page_id": page_id, "page_data": row_list})

    return page_list

def extract_auto_tables(self,df_pdf_data,filename,extract_by_page: bool = True):
        # group text that is in the same line and count number of element in each group
        df_pdf_data["bbox.y0_rounded"] = df_pdf_data["bbox.y0"].apply(lambda x: mt.floor(x))
        df_pdf_data_group = df_pdf_data.groupby(["page_num", "bbox.y0_rounded"])
        df_pdf_data_group_count = df_pdf_data_group["bbox.x0"].count().rename("count_row_cols").reset_index()
        df_pdf_data_group_count = df_pdf_data_group_count.sort_values(by=["page_num", "bbox.y0_rounded"],
                                                                        ascending=[True,False])
        # Max columns per page
        df_pdf_data_group_page = df_pdf_data_group_count.groupby(["page_num"])
        df_pdf_data_group_count_page = df_pdf_data_group_page["count_row_cols"].max().rename("max_cols_per_page").reset_index()
        df_pdf_data_group_count_page = df_pdf_data_group_count_page.sort_values(by=["page_num"], ascending=[True])

        # Merge with main data
        df_pdf_data_merge = pd.merge(df_pdf_data_group_count,
                                        df_pdf_data,
                                        on=["page_num", "bbox.y0_rounded"],
                                        how="left")

        df_pdf_data_merge = pd.merge(df_pdf_data_group_count_page,
                                        df_pdf_data_merge,
                                        on=["page_num"],
                                        how="left")

        df_pdf_data_merge = df_pdf_data_merge.sort_values(by=["page_num", "bbox.y0", "bbox.x0"],
                                                            ascending=[True, False, True])

        #Define group of data
        df_pdf_data_merge["is_table"] = df_pdf_data_merge.count_row_cols.apply(lambda x: 1 if x>1 else 0)
        df_pdf_data_merge["group_id"] = 0
        df_pdf_data_merge["direction"] = "dataframe"

        if extract_by_page:
            df_pdf_data_merge_count_by_page = (df_pdf_data_merge
                                                .groupby("page_num")
                                                .agg({"is_table":"sum",
                                                        "text": "count"})
                                                .reset_index()
                                                )
            df_pdf_data_merge_count_by_page.columns = ["page_num","count_tables","count_all"]
            df_pdf_data_merge_count_by_page["table_ratio"] = (df_pdf_data_merge_count_by_page.count_tables/df_pdf_data_merge_count_by_page.count_all)
            df_pdf_data_merge = pd.merge(df_pdf_data_merge_count_by_page,
                                            df_pdf_data_merge,
                                            on=["page_num"],
                                            how="left")

            TABLE_TRESHOLD = 0.5
            df_pdf_data_merge["direction"] = df_pdf_data_merge.table_ratio.apply(lambda x: "dataframe" if x>TABLE_TRESHOLD else "text")


        else:
            group_id=0
            prev_row = None
            max_row = len(df_pdf_data_merge)

            #Shift prev and next
            df_pdf_data_merge["prev_1_page_num"]=df_pdf_data_merge.page_num.shift(1)
            df_pdf_data_merge["prev_1_is_table"]=df_pdf_data_merge.is_table.shift(1)
            df_pdf_data_merge["next_1_page_num"]=df_pdf_data_merge.page_num.shift(-1)
            df_pdf_data_merge["next_1_is_table"]=df_pdf_data_merge.is_table.shift(-1)
            df_pdf_data_merge["next_2_page_num"]=df_pdf_data_merge.page_num.shift(-2)
            df_pdf_data_merge["next_2_is_table"]=df_pdf_data_merge.is_table.shift(-2)

            current_is_table = None
            for i, row in df_pdf_data_merge.iterrows():
                if i != 0:
                    #Compare current row with previous row and with 2 next rows:
                    # If text is embeded within a dataframe then include text to dataframe
                    if (row["prev_1_page_num"] == row["page_num"]
                        and current_is_table == row["is_table"]
                    ) or (row["prev_1_page_num"] == row["next_1_page_num"]
                            and current_is_table == row["next_1_is_table"]
                    )or (row["prev_1_page_num"] == row["next_2_page_num"]
                            and current_is_table == row["next_2_is_table"]

                    ):
                        df_pdf_data_merge.at[i, "group_id"] = group_id
                        df_pdf_data_merge.at[i, "is_table"] = current_is_table
                        df_pdf_data_merge.at[i+1, "prev_1_is_table"] = current_is_table
                    else:
                        current_is_table = row["is_table"]
                        group_id += 1
                        df_pdf_data_merge.at[i, "group_id"] = group_id

            df_pdf_data_merge["direction"] = df_pdf_data_merge.is_table.apply(lambda x: "text" if x==0 else "dataframe")

        df_pdf_data_merge["section_name"] = df_pdf_data_merge.apply(lambda x: f"Page-{x.page_num}_group-{x.group_id}",
                                                                    axis=1)


        df_pdf_data_merge_group = df_pdf_data_merge.groupby(["page_num",
                                                                "section_name",
                                                                "direction"
                                                                ]).agg({"bbox.x0": "min",
                                                                        "bbox.x1": "max",
                                                                        "bbox.y0": "max",
                                                                        "bbox.y1": "min"}).reset_index()

        # PROCESS file content
        list_data = []
        table_areas = ["0,755,755,0"]
        for i, row in df_pdf_data_merge_group.iterrows():
            if extract_by_page == False:
                table_areas = [f"{row['bbox.x0']-10},{row['bbox.y0']+10},{row['bbox.x1']+10},{row['bbox.y1']-10}"]
            tables = camelot.read_pdf(
                os.path.join(self.current_app_config.input_path, filename),
                pages=f"{row['page_num']}",
                flavor="stream",
                table_areas=table_areas,
                strip_text="\n",
                flag_size=True,
                split_text=False,
                col_tol=100,
                suppress_stdout=True
            )
            #Concatenate result to previous subpages: This manage sections that cross multiple pages
            temp_df = tables[0].df
            if not temp_df.empty:
                data_content = temp_df.to_dict(orient="records")
                if row["direction"] == "text":
                    data_content = self.concat_list_to_string(data_content)

                list_data.append({"page_num": row["page_num"],
                                    "section_id": i,
                                    "section_name": row["section_name"],
                                    "direction": row["direction"],
                                    "data_list": data_content
                                    }
                                    )


        # Add processed report content to result list
        procesed_file_content = {
            "source_filename": filename,
            "process_date": str(datetime.date.today()),
            "total_pages": str(df_pdf_data_merge.page_num.max()),
            "report_type": "Auto-Extraction",
            "report_content": list_data,
        }

        return procesed_file_content