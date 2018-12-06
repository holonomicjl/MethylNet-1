import rpy2.robjects as robjects
import rpy2.interactive as r
import rpy2.robjects.packages as rpackages
from rpy2.robjects.packages import importr
import os, subprocess
import click
import glob
import numpy as np, pandas as pd
from collections import Counter
#import impyute
from functools import reduce
from rpy2.robjects import pandas2ri, numpy2ri
import sqlite3
import pickle
pandas2ri.activate()
numpy2ri.activate()
# fixme dump to sql db!!

CONTEXT_SETTINGS = dict(help_option_names=['-h','--help'], max_content_width=90)

@click.group(context_settings= CONTEXT_SETTINGS)
@click.version_option(version='0.1')
def preprocess():
    pass

class PackageInstaller:
    def __init__(self):
        pass

    def install_bioconductor(self):
        #robjects.r['install.packages']("BiocInstaller",repos="http://bioconductor.org/packages/3.7/bioc")
        base = importr('base')
        base.source("http://www.bioconductor.org/biocLite.R")

    def install_tcga_biolinks(self):
        #robjects.r('source("https://bioconductor.org/biocLite.R")\n')
        biocinstaller = importr("BiocInstaller")
        biocinstaller.biocLite("TCGAbiolinks")

    def install_minfi_others(self):
        biocinstaller = importr("BiocInstaller")
        biocinstaller.biocLite(robjects.vectors.StrVector(["minfi","ENmix",
                                "minfiData","sva","GEOquery","geneplotter"]))

class TCGADownloader:
    def __init__(self):
        pass

        """utils = rpackages.importr('utils')
        utils.chooseCRANmirror(ind=1)
        packnames=('TCGAbiolinks',)
        from rpy2.robjects.vectors import StrVector
        names_to_install = [x for x in packnames if not rpackages.isinstalled(x)]
        if len(names_to_install) > 0:
            utils.install_packages(StrVector(names_to_install))"""

    def download_tcga(self, output_dir):
        tcga = importr("TCGAbiolinks")
        print(tcga)
        robjects.r("""
                   library(TCGAbiolinks)
                   projects <- TCGAbiolinks:::getGDCprojects()$project_id
                   projects <- projects[grepl('^TCGA',projects,perl=T)]
                   match.file.cases.all <- NULL
                   for(proj in projects){
                        print(proj)
                        query <- GDCquery(project = proj,
                                          data.category = "Raw microarray data",
                                          data.type = "Raw intensities",
                                          experimental.strategy = "Methylation array",
                                          legacy = TRUE,
                                          file.type = ".idat",
                                          platform = "Illumina Human Methylation 450")
                        match.file.cases <- getResults(query,cols=c("cases","file_name"))
                        match.file.cases$project <- proj
                        match.file.cases.all <- rbind(match.file.cases.all,match.file.cases)
                        tryCatch(GDCdownload(query, method = "api", files.per.chunk = 20),
                                 error = function(e) GDCdownload(query, method = "client"))
                    }
                    # This will create a map between idat file name, cases (barcode) and project
                    readr::write_tsv(match.file.cases.all, path =  "idat_filename_case.txt")
                    # code to move all files to local folder
                    for(file in dir(".",pattern = ".idat", recursive = T)){
                        TCGAbiolinks:::move(file,file.path('%s',basename(file)))
                    }
                   """%output_dir)

    def download_clinical(self, output_dir):
        robjects.r("""
                   library(TCGAbiolinks)
                   library(data.table)
                   projects <- TCGAbiolinks:::getGDCprojects()$project_id
                   projects <- projects[grepl('^TCGA',projects,perl=T)]
                   match.file.cases.all <- NULL
                   data <- list()
                   for(n in 1:length(projects)){
                        proj <- projects[n]
                        print(proj)
                        clin.query <- GDCquery_clinic(project = proj,
                                          type='clinical', save.csv=F)
                        #tryCatch(GDCdownload(clin.query, method='api'),
                        #    error = function(e) {GDCdownload(clin.query, method='client')})
                        #tryCatch(clinical.patient <- GDCprepare_clinic(clin.query, clinical.info = "patient"),
                        #    error = function(e) {0})
                        data[[length(data)+1]] = clin.query
                    }
                    df <- rbindlist(data)
                    write.csv(df, file=file.path('%s','clinical_info.csv'))
                   """%output_dir)

    def download_geo(self, query, output_dir):
        """library(GEOquery)"""
        #import GEOparse
        base=importr('base')
        geo = importr("GEOquery")
        geo.getGEOSuppFiles(query)
        robjects.r["untar"]("{0}/{0}_RAW.tar".format(query), exdir = "{}/idat".format(query))
        idatFiles = robjects.r('list.files("{}/idat", pattern = "idat.gz$", full = TRUE)'.format(query))
        robjects.r["sapply"](idatFiles, robjects.r["gunzip"], overwrite = True)
        subprocess.call('mv {}/idat/*.idat {}/'.format(query, output_dir),shell=True)
        # FIXME Table, dataTable import
        pandas2ri.ri2py(robjects.r['as'](robjects.r('phenoData')(robjects.r("getGEO('{}')[[1]]".format(query))),'data.frame')).to_csv('{}/{}_clinical_info.csv'.format(output_dir,query))# ,GSEMatrix = FALSE
        # geo_query="GSE109381"
        # geo = importr("GEOquery")
        # base=importr('base')
        # g=robjects.r("getGEO('{}')".format(geo_query))
        # dollar = base.__dict__["$"]
        # dollar(g, "phenoData")
        # robjects.r['as'](robjects.r('phenoData')(g),'data.frame')

class PreProcessPhenoData:
    def __init__(self, pheno_sheet, idat_dir, header_line=0): # source: geo, tcga, custom
        self.xlsx = True if pheno_sheet.endswith('.xlsx') or pheno_sheet.endswith('.xls') else False
        if self.xlsx:
            self.pheno_sheet = pd.read_excel(pheno_sheet,header=header_line)
        else:
            self.pheno_sheet = pd.read_csv(pheno_sheet, header=header_line)
        self.idat_dir = idat_dir

    def format_geo(self, disease_class_column="methylation class:ch1", include_columns={}):
        idats = glob.glob("{}/*.idat".format(self.idat_dir))
        idat_basenames = np.unique(np.vectorize(lambda x: '_'.join(x.split('/')[-1].split('_')[:3]))(idats))
        idat_geo_map = dict(zip(np.vectorize(lambda x: x.split('_')[0])(idat_basenames),np.array(idat_basenames)))
        self.pheno_sheet['Basename'] = self.pheno_sheet['geo_accession'].map(idat_geo_map)
        self.pheno_sheet = self.pheno_sheet[self.pheno_sheet['Basename'].isin(idat_basenames)]
        self.pheno_sheet.loc[:,'Basename'] = self.pheno_sheet['Basename'].map(lambda x: self.idat_dir+x)
        col_dict = {'geo_accession':'AccNum',disease_class_column:'disease'}
        col_dict.update(include_columns)
        self.pheno_sheet = self.pheno_sheet[['Basename','geo_accession',disease_class_column]+(list(include_columns.keys()) if include_columns else [])].rename(columns=col_dict)


    def format_tcga(self, mapping_file="barcode_mapping.txt"):
        idats = glob.glob("{}/*.idat".format(self.idat_dir))
        barcode_mappings = np.loadtxt(mapping_file,dtype=str)
        barcode_mappings[:,1] = np.vectorize(lambda x: '-'.join(x.split('-')[:4]))(barcode_mappings[:,1])
        barcode_mappings = {v:k for k,v in dict(barcode_mappings.tolist()).items()}
        self.pheno_sheet['Basename'] = self.pheno_sheet['bcr_patient_barcode'].map(barcode_mappings)
        idat_basenames = np.unique(np.vectorize(lambda x: '_'.join(x.split('/')[-1].split('_')[:2]))(idats))
        self.pheno_sheet = self.pheno_sheet[self.pheno_sheet['Basename'].isin(idat_basenames)]
        self.pheno_sheet.loc[:,['Basename']] = self.pheno_sheet['Basename'].map(lambda x: self.idat_dir+x)
        self.pheno_sheet = self.pheno_sheet[['Basename', 'disease', 'tumor_stage', 'vital_status', 'age_at_diagnosis', 'gender', 'race', 'ethnicity']].rename(columns={'tumor_stage':'stage','vital_status':'vital','age_at_diagnosis':'age'})

    def format_custom(self, basename_col, disease_class_column, include_columns={}):
        idats = glob.glob("{}/*.idat".format(self.idat_dir))
        idat_basenames = np.unique(np.vectorize(lambda x: '_'.join(x.split('/')[-1].split('_')[:-1]))(idats))
        idat_count_underscores = np.vectorize(lambda x: x.count('_'))(idat_basenames)
        self.pheno_sheet['Basename'] = self.pheno_sheet[basename_col]
        basename_count_underscores = np.vectorize(lambda x: x.count('_'))(self.pheno_sheet['Basename'])
        min_underscores=min(np.hstack([idat_count_underscores,basename_count_underscores]))
        basic_basename_fn = np.vectorize(lambda x: '_'.join(x.split('_')[-min_underscores-1:]))
        basic_basename=dict(zip(basic_basename_fn(self.pheno_sheet['Basename']),self.pheno_sheet['Basename'].values))
        basic_idat=dict(zip(basic_basename_fn(idat_basenames),idat_basenames))
        complete_mapping={basic_basename[basename]:basic_idat[basename] for basename in basic_basename}
        self.pheno_sheet.loc[:,'Basename']=self.pheno_sheet['Basename'].map(complete_mapping).map(lambda x: self.idat_dir+x)
        self.pheno_sheet['disease'] = self.pheno_sheet[disease_class_column]
        self.pheno_sheet = self.pheno_sheet[np.unique(['Basename', 'disease']+list(include_columns.keys()))].rename(columns=include_columns)

    def merge(self, other_formatted_sheet, use_second_sheet_disease=True):
        disease_dict = {False:'disease_x',True:'disease_y'}
        self.pheno_sheet = self.pheno_sheet.merge(other_formatted_sheet.pheno_sheet,how='inner', on='Basename')
        self.pheno_sheet['disease'] = self.pheno_sheet[disease_dict[use_second_sheet_disease]]
        cols=list(self.pheno_sheet)
        self.pheno_sheet = self.pheno_sheet[[col for col in cols if col!='Unnamed: 0_x' and col!='Unnamed: 0_y' and col!=disease_dict[use_second_sheet_disease]]]

    def concat(self, other_formatted_sheet):
        self.pheno_sheet=pd.concat([self.pheno_sheet,other_formatted_sheet.pheno_sheet],join='inner').reset_index(drop=True)
        self.pheno_sheet=self.pheno_sheet[[col for col in list(self.pheno_sheet) if not col.startswith('Unnamed:')]]

    def export(self, output_sheet_name):
        self.pheno_sheet.to_csv(output_sheet_name)
        print("Please move all other sample sheets out of this directory.")

    def get_categorical_distribution(self, key, disease_only=False, subtype_delimiter=','):
        if disease_only:
            self.pheno_sheet['disease_only'] = self.pheno_sheet['disease'].map(lambda x: x.split(',')[0])
            key='disease_only'
        return Counter(self.pheno_sheet[key])

    def remove_diseases(self,exclude_disease_list, low_count, disease_only,subtype_delimiter):
        if low_count:
            count_diseases=pd.DataFrame(self.get_categorical_distribution(low_count, disease_only,subtype_delimiter).items(),columns=['disease','count'])
            exclude_diseases_more=count_diseases.loc[count_diseases['count']<low_count,['disease']].unique().tolist()
            if disease_only:
                exclude_diseases_more=self.pheno_sheet.loc[self.pheno_sheet['disease_only'].isin(exclude_diseases_more),'disease'].unique().tolist()
        else:
            exclude_diseases_more=[]
        self.pheno_sheet = self.pheno_sheet[~self.pheno_sheet['disease'].isin(exclude_disease_list+exclude_diseases_more)]


class PreProcessIDAT:
    # https://kasperdanielhansen.github.io/genbioconductor/html/minfi.html
    # https://www.bioconductor.org/help/course-materials/2015/BioC2015/methylation450k.html#dependencies
    def __init__(self, idat_dir):
        self.idat_dir = idat_dir # can establish cases and controls
        self.minfi = importr('minfi')
        self.enmix = importr("ENmix")


    def load_idats(self, geo_query=''): # maybe have a larger parent class that subsets idats by subtype, then preprocess each subtype and combine the dataframes
        targets = self.minfi.read_metharray_sheet(self.idat_dir)
        self.RGset = self.minfi.read_metharray_exp(targets=targets, extended=True)
        if geo_query:
            geo = importr('GEOquery')
            self.RGset.slots["pData"] = robjects.r('pData')(robjects.r("getGEO('{}')[[1]]".format(query)))
            #print(self.RGset.slots["pData"])
        #robjects.r("""targets <- read.450k.sheet({})
        #    sub({}, "", targets$Basename)
        #    RGset <- read.450k.exp(base = {}, targets = targets)""".format(self.idat_dir))
        #self.RGset = robjects.globalenv['RGset']
        return self.RGset

    def preprocessRAW(self):
        self.MSet = self.minfi.preprocessRaw(self.RGset)
        return self.MSet

    def preprocessENmix(self, n_cores=6):
        self.qcinfo = self.enmix.QCinfo(self.RGset, detPthre=1e-7)
        self.MSet = self.enmix.preprocessENmix(self.RGset, QCinfo=self.qcinfo, nCores=n_cores)
        self.MSet = self.enmix.QCfilter(self.MSet,qcinfo=self.qcinfo,outlier=True)
        return self.MSet

    def return_beta(self):
        self.RSet = self.minfi.ratioConvert(self.MSet, what = "both", keepCN = True)
        return self.RSet

    def get_beta(self):
        self.beta = self.minfi.getBeta(self.RSet)
        return self.beta

    def filter_beta(self):
        self.beta_final=self.enmix.rm_outlier(self.beta,qcscore=self.qcinfo)
        return self.beta_final

    def plot_qc_metrics(self, output_dir):
        self.enmix.plotCtrl(self.RGset)
        grdevice = importr("grDevices")
        geneplotter = importr("geneplotter")
        base = importr('base')
        anno=self.minfi.getAnnotation(self.RGset)
        #self.enmix.multifreqpoly(self.get_meth()+self.get_unmeth(), xlab="Total intensity")
        anno_py = pandas2ri.ri2py(robjects.r['as'](anno,'data.frame'))
        beta_py = pandas2ri.ri2py(self.beta)
        #print(beta_py)
        beta1=numpy2ri.py2ri(beta_py[anno_py["Type"]=="I"])
        beta2=numpy2ri.py2ri(beta_py[anno_py["Type"]=="II"])
        grdevice.jpeg(output_dir+'/dist.jpg',height=900,width=600)
        base.par(mfrow=robjects.vectors.IntVector([3,2]))
        self.enmix.multidensity(self.beta, main="Multidensity")
        self.enmix.multifreqpoly(self.beta, xlab="Beta value")
        self.enmix.multidensity(beta1, main="Multidensity: Infinium I")
        self.enmix.multifreqpoly(beta1, main="Multidensity: Infinium I", xlab="Beta value")
        self.enmix.multidensity(beta2, main="Multidensity: Infinium II")
        self.enmix.multifreqpoly(beta2, main="Multidensity: Infinium II", xlab="Beta value")
        grdevice.dev_off()
        self.minfi.qcReport(self.RGset, pdf = "{}/qcReport.pdf".format(output_dir))  # sampNames = pheno$X_SAMPLE_ID, sampGroups = pheno$sample.type,
        self.minfi.mdsPlot(self.RGset)#, sampNames = pheno$X_SAMPLE_ID, sampGroups = pheno$sample.type)
        self.minfi.densityPlot(self.RGset, main='Beta', xlab='Beta')#, sampGroups = pheno$sample.type, main = "Beta", xlab = "Beta")

    def get_meth(self):
        return self.minfi.getMeth(self.MSet)

    def get_unmeth(self):
        return self.minfi.getUnmeth(self.MSet)

    def extract_pheno_data(self, methylset=False):
        self.pheno = robjects.r("pData")(self.MSet) if methylset else robjects.r("pData")(self.RGset)
        return self.pheno

    def extract_manifest(self):
        self.manifest = self.minfi.getManifest(self.RGset)
        return self.manifest

    def preprocess(self, geo_query='', n_cores=6):
        self.load_idats(geo_query)
        self.preprocessENmix(n_cores)
        self.return_beta()
        self.get_beta()
        self.filter_beta()
        self.extract_pheno_data(methylset=True)
        return self.pheno, self.beta_final

    def plot_original_qc(self, output_dir):
        self.preprocessRAW()
        self.return_beta()
        self.get_beta()
        self.plot_qc_metrics(output_dir)

    def output_pheno_beta(self):
        self.pheno_py=pandas2ri.ri2py(robjects.r['as'](self.pheno,'data.frame'))
        self.beta_py=pd.DataFrame(pandas2ri.ri2py(self.beta_final),index=numpy2ri.ri2py(robjects.r("featureNames")(self.RSet)),columns=numpy2ri.ri2py(robjects.r("sampleNames")(self.RSet))).transpose()

    def export_pickle(self, output_pickle, disease=''):
        output_dict = {}
        if os.path.exists(output_pickle):
            output_dict = pickle.load(open(output_pickle,'rb'))
        output_dict['pheno' if not disease else 'pheno_{}'.format(disease)] = self.pheno_py
        output_dict['beta' if not disease else 'beta_{}'.format(disease)] = self.beta_py
        pickle.dump(output_dict, open(output_pickle,'wb'))

    def export_sql(self, output_db, disease=''):
        conn = sqlite3.connect(output_db)#'{}/methyl_array.db'.format(output_dir))
        self.pheno_py.to_sql('pheno' if not disease else 'pheno_{}'.format(disease), con=conn, if_exists='replace')
        self.beta_py.to_sql('beta' if not disease else 'beta_{}'.format(disease), con=conn, if_exists='replace')
        conn.close()

    def export_csv(self, output_dir):
        self.pheno_py.to_csv('{}/pheno.csv'.format(output_dir))
        self.beta_py.to_csv('{}/beta.csv'.format(output_dir))


class MethylationArray: # FIXME arrays should be samplesxCpG or samplesxpheno_data, rework indexing
    def __init__(self, pheno_df, beta_df, name=''):
        self.pheno=pheno_df
        self.beta=beta_df
        self.name=name

    def export(self, output_pickle):
        pass

    def write_csvs(self, output_dir):
        self.pheno.to_csv('{}/pheno.csv'.format(output_dir))
        self.beta.to_csv('{}/beta.csv'.format(output_dir))

    def write_pickle(self, output_pickle, disease=''):
        output_dict = {}
        if os.path.exists(output_pickle):
            output_dict = pickle.load(open(output_pickle,'rb'))
        output_dict['pheno' if not disease else 'pheno_{}'.format(disease)] = self.pheno
        output_dict['beta' if not disease else 'beta_{}'.format(disease)] = self.beta
        pickle.dump(output_dict, open(output_pickle,'wb'))

    def write_db(self, conn, disease=''):
        self.pheno.to_sql('pheno' if not disease else 'pheno_{}'.format(disease), con=conn, if_exists='replace')
        self.beta.to_sql('beta' if not disease else 'beta_{}'.format(disease), con=conn, if_exists='replace')

    def impute(self, imputer):
        self.beta = pd.DataFrame(imputer.fit_transform(self.beta),index=self.beta.index,columns=list(self.beta))

    def return_shape(self):
        return self.beta.shape

    def split_train_test(self, train_p=0.8):
        np.random.seed(42)
        methyl_array_idx = pd.Series(self.pheno.index)
        #np.random.shuffle(methyl_array_idx)
        train_idx = methyl_array_idx.sample(frac=train_p)
        test_idx = methyl_array_idx.drop(train_idx.index)
        return MethylationArray(self.pheno.loc[train_idx.values],self.beta.loc[train_idx.values,:],'train'),MethylationArray(self.pheno.loc[test_idx.values],self.beta.loc[test_idx.values,:],'test')

    def split_by_subtype(self, write_pkl=False, out_pkl=None):
        methyl_arrays = []
        for disease, pheno_df in self.pheno.groupby('diseases'):
            new_disease_name = disease.replace(' ','')
            beta_df = self.beta.loc[:,pheno_df.index]
            methyl_arrays.append(MethylationArray(pheno_df,beta_df,new_disease_name))
        methyl_arrays = MethylationArrays(methyl_arrays)
        if write_pkl and out_pkl != None:
            methyl_arrays.write_pkls(out_pkl)
        return methyl_arrays

    def mad_filter(self, n_top_cpgs):
        mad_cpgs = self.beta.mad(axis=0).sort_values(ascending=False)
        top_mad_cpgs = np.array(list(mad_cpgs.iloc[:n_top_cpgs].index))
        self.beta = self.beta.loc[:, top_mad_cpgs]

    def merge_preprocess_sheet(self, preprocess_sample_df):
        self.pheno=self.pheno.merge(preprocess_sample_df,on=['Basename'],how='inner')
        if 'disease_x' in list(self.pheno):
            self.pheno = self.pheno.rename(columns={'disease_x':'disease'})
        self.pheno = self.pheno[[col for col in list(self.pheno) if not col.startswith('Unnamed:')]]
        self.pheno=self.pheno.set_index([np.vectorize(lambda x: x.split('/')[-1])(self.pheno['Basename'])],drop=False)

    def load(self, input_pickle):
        pass

class MethylationArrays:
    def __init__(self, list_methylation_arrays):
        self.methylation_arrays = list_methylation_arrays

    def combine(self): # FIXME add sort based on samples
        pheno_df=pd.concat([methylArr.pheno for methylArr in self.methylation_arrays], join='inner')#.sort()
        beta_df=pd.concat([methylArr.beta for methylArr in self.methylation_arrays], join='inner')#.sort()
        return MethylationArray(pheno_df,beta_df)

    def write_dbs(self, conn):
        for methyl_arr in self.methylation_arrays:
            methyl_arr.write_db(conn, methyl_arr.name)

    def write_pkls(self,pkl):
        for methyl_arr in self.methylation_arrays:
            methyl_arr.write_pickle(pkl, methyl_arr.name)

    def impute(self, imputer):
        for i in range(len(self.methylation_arrays)):
            self.methylation_arrays[i].impute(imputer)

class ImputerObject:
    def __init__(self, solver, method, opts={}):
        from fancyimpute import KNN, NuclearNormMinimization, SoftImpute, IterativeImputer, BiScaler
        from sklearn.impute import SimpleImputer
        import inspect
        imputers = {'fancyimpute':dict(KNN=KNN,MICE=IterativeImputer,BiScaler=BiScaler,Soft=SoftImpute),
                    'impyute':dict(),
                    'simple':dict(Mean=SimpleImputer(strategy='mean'),Zero=SimpleImputer(strategy='constant'))}
        try:
            if solver == 'fancyimpute':
                f=imputers[solver][method]
                opts={key: opts[key] for key in opts if key in inspect.getargspec(f.__init__)[0]}
                self.imputer=f(**opts)
            else:
                self.imputer = imputers[solver][method]
        except:
            print('{} {} not a valid combination.\nValid combinations:{}'.format(
                solver, method, '\n'.join('{}:{}'.format(solver,','.join(imputers[solver].keys())) for solver in imputers)))
            exit()

    def return_imputer(self):
        return self.imputer

#### FUNCTIONS ####

def extract_pheno_beta_df_from_folder(folder):
    return pd.read_csv(folder+'/pheno.csv'), pd.read_csv(folder+'/beta.csv')

def extract_pheno_beta_df_from_pickle_dict(input_dict, disease=''):
    if disease:
        return input_dict['pheno_{}'.format(disease)], input_dict['beta_{}'.format(disease)]
    else:
        return input_dict['pheno'], input_dict['beta']

def extract_pheno_beta_df_from_sql(conn, disease=''):
    if disease:
        return pd.read_sql('select * from {};'.format('pheno_{}'.format(disease)),conn), pd.read_sql('select * from {};'.format('beta_{}'.format(disease)),conn)
    else:
        return pd.read_sql('select * from {};'.format('pheno'),conn), pd.read_sql('select * from {};'.format('beta'),conn)

#### COMMANDS ####

## Install ##
@preprocess.command()
def install_bioconductor():
    installer = PackageInstaller()
    installer.install_bioconductor()

@preprocess.command()
def install_minfi_others():
    installer = PackageInstaller()
    installer.install_minfi_others()

@preprocess.command()
def install_tcga_biolinks():
    installer = PackageInstaller()
    installer.install_tcga_biolinks()

## Download ##

@preprocess.command()
@click.option('-o', '--output_dir', default='./tcga_idats/', help='Output directory for exported idats.', type=click.Path(exists=False), show_default=True)
def download_tcga(output_dir):
    os.makedirs(output_dir, exist_ok=True)
    downloader = TCGADownloader()
    downloader.download_tcga(output_dir)

@preprocess.command()
@click.option('-o', '--output_dir', default='./tcga_idats/', help='Output directory for exported idats.', type=click.Path(exists=False), show_default=True)
def download_clinical(output_dir):
    os.makedirs(output_dir, exist_ok=True)
    downloader = TCGADownloader()
    downloader.download_clinical(output_dir)

@preprocess.command()
@click.option('-g', '--geo_query', default='', help='GEO study to query.', type=click.Path(exists=False), show_default=True)
@click.option('-o', '--output_dir', default='./geo_idats/', help='Output directory for exported idats.', type=click.Path(exists=False), show_default=True)
def download_geo(geo_query,output_dir):
    os.makedirs(output_dir, exist_ok=True)
    downloader = TCGADownloader()
    downloader.download_geo(geo_query,output_dir)

@preprocess.command()
@click.option('-is', '--input_sample_sheet', default='./tcga_idats/clinical_info.csv', help='Clinical information downloaded from tcga/geo/custom.', type=click.Path(exists=False), show_default=True)
@click.option('-s', '--source_type', default='tcga', help='Source type of data.', type=click.Choice(['tcga','geo','custom']), show_default=True)
@click.option('-i', '--idat_dir', default='./tcga_idats/', help='Idat directory.', type=click.Path(exists=False), show_default=True)
@click.option('-os', '--output_sample_sheet', default='./tcga_idats/minfiSheet.csv', help='CSV for minfi input.', type=click.Path(exists=False), show_default=True)
@click.option('-m', '--mapping_file', default='./barcode_mapping.txt', help='Mapping file from uuid to TCGA barcode.', type=click.Path(exists=False), show_default=True)
@click.option('-l', '--header_line', default=0, help='Line to begin reading csv/xlsx.', show_default=True)
@click.option('-d', '--disease_class_column', default="methylation class:ch1", help='Disease classification column, for custom and geo datasets.', type=click.Path(exists=False), show_default=True)
@click.option('-b', '--basename_col', default="Sentrix ID (.idat)", help='Basename classification column, for custom datasets.', type=click.Path(exists=False), show_default=True)
@click.option('-c', '--include_columns_file', default="", help='Custom columns file containing columns to keep, separated by \\n. Add a tab for each line if you wish to rename columns: original_name \\t new_column_name', type=click.Path(exists=False), show_default=True)
def create_sample_sheet(input_sample_sheet, source_type, idat_dir, output_sample_sheet, mapping_file, header_line, disease_class_column, basename_col, include_columns_file):
    os.makedirs(output_sample_sheet[:output_sample_sheet.rfind('/')], exist_ok=True)
    pheno_sheet = PreProcessPhenoData(input_sample_sheet, idat_dir, header_line= (0 if source_type != 'custom' else header_line))
    if include_columns_file:
        include_columns=np.loadtxt(include_columns_file,dtype=str,delimiter='\t')
        if '\t' in open(include_columns_file).read() and len(include_columns.shape)<2:
            include_columns=dict(include_columns[np.newaxis,:].tolist())
        elif len(include_columns.shape)<2:
            include_columns=dict(zip(include_columns,include_columns))
        else:
            include_columns=dict(include_columns.tolist())
    else:
        include_columns={}
    if source_type == 'tcga':
        pheno_sheet.format_tcga(mapping_file)
    elif source_type == 'geo':
        pheno_sheet.format_geo(disease_class_column, include_columns)
    else:
        pheno_sheet.format_custom(basename_col, disease_class_column, include_columns)
    pheno_sheet.export(output_sample_sheet)
    print("Please remove {} from {}, if it exists in that directory.".format(input_sample_sheet, idat_dir))

@preprocess.command()
@click.option('-s1', '--sample_sheet1', default='./tcga_idats/clinical_info1.csv', help='Clinical information downloaded from tcga/geo/custom, formatted using create_sample_sheet.', type=click.Path(exists=False), show_default=True)
@click.option('-s2', '--sample_sheet2', default='./tcga_idats/clinical_info2.csv', help='Clinical information downloaded from tcga/geo/custom, formatted using create_sample_sheet.', type=click.Path(exists=False), show_default=True)
@click.option('-os', '--output_sample_sheet', default='./tcga_idats/minfiSheet.csv', help='CSV for minfi input.', type=click.Path(exists=False), show_default=True)
@click.option('-d', '--second_sheet_disease', is_flag=True, help='Use second sheet\'s disease column.')
def merge_sample_sheets(sample_sheet1, sample_sheet2, output_sample_sheet, second_sheet_disease):
    s1 = PreProcessPhenoData(sample_sheet1, idat_dir='', header_line=0)
    s2 = PreProcessPhenoData(sample_sheet2, idat_dir='', header_line=0)
    s1.merge(s2,second_sheet_disease)
    s1.export(output_sample_sheet)

@preprocess.command()
@click.option('-s1', '--sample_sheet1', default='./tcga_idats/clinical_info1.csv', help='Clinical information downloaded from tcga/geo/custom, formatted using create_sample_sheet.', type=click.Path(exists=False), show_default=True)
@click.option('-s2', '--sample_sheet2', default='./tcga_idats/clinical_info2.csv', help='Clinical information downloaded from tcga/geo/custom, formatted using create_sample_sheet.', type=click.Path(exists=False), show_default=True)
@click.option('-os', '--output_sample_sheet', default='./tcga_idats/minfiSheet.csv', help='CSV for minfi input.', type=click.Path(exists=False), show_default=True)
def concat_sample_sheets(sample_sheet1, sample_sheet2, output_sample_sheet):
    # FIXME add ability to concat more sample sheets; dump to sql!!!
    s1 = PreProcessPhenoData(sample_sheet1, idat_dir='', header_line=0)
    s2 = PreProcessPhenoData(sample_sheet2, idat_dir='', header_line=0)
    s1.concat(s2)
    s1.export(output_sample_sheet)

@preprocess.command()
@click.option('-is', '--formatted_sample_sheet', default='./tcga_idats/minfiSheet.csv', help='Clinical information downloaded from tcga/geo/custom, formatted using create_sample_sheet.', type=click.Path(exists=False), show_default=True)
@click.option('-k', '--key', default='disease', help='Column of csv to print statistics for.', type=click.Path(exists=False), show_default=True)
@click.option('-d', '--disease_only', is_flag=True, help='Only look at disease, or text before subtype_delimiter.')
@click.option('-sd', '--subtype_delimiter', default=',', help='Delimiter for disease extraction.', type=click.Path(exists=False), show_default=True)
def get_categorical_distribution(formatted_sample_sheet,key,disease_only=False,subtype_delimiter=','):
    print('\n'.join('{}:{}'.format(k,v) for k,v in PreProcessPhenoData(formatted_sample_sheet, idat_dir='', header_line=0).get_categorical_distribution(key,disease_only,subtype_delimiter).items()))

@preprocess.command()
@click.option('-is', '--formatted_sample_sheet', default='./tcga_idats/clinical_info.csv', help='Clinical information downloaded from tcga/geo/custom, formatted using create_sample_sheet.', type=click.Path(exists=False), show_default=True)
@click.option('-e', '--exclude_disease_list', default='', help='List of conditions to exclude, from disease column.', type=click.Path(exists=False), show_default=True)
@click.option('-os', '--output_sample_sheet', default='./tcga_idats/minfiSheet.csv', help='CSV for minfi input.', type=click.Path(exists=False), show_default=True)
@click.option('-l', '--low_count', default=0, help='Remove diseases if they are below a certain count, default this is not used.', type=click.Path(exists=False), show_default=True)
@click.option('-d', '--disease_only', is_flag=True, help='Only look at disease, or text before subtype_delimiter.')
@click.option('-sd', '--subtype_delimiter', default=',', help='Delimiter for disease extraction.', type=click.Path(exists=False), show_default=True)
def remove_diseases(formatted_sample_sheet, exclude_disease_list, output_sheet_name, low_count, disease_only=False,subtype_delimiter=','):
    exclude_disease_list = exclude_disease_list.split(',')
    pData = PreProcessPhenoData(formatted_sample_sheet, idat_dir='', header_line=0)
    pData.remove_diseases(exclude_disease_list,low_count, disease_only,subtype_delimiter)
    pData.export(output_sheet_name)
    print("Please remove {} from idat directory, if it exists in that directory.".format(formatted_sample_sheet))


### TODO: Wrap a class around following functions ###

def print_case_controls():
    """Print number of case and controls for subtypes"""
    pass

def remove_controls():
    """Remove controls for study"""
    pass

def remove_low_sample_number():
    """Remove cases for study with low sample number"""
    pass

## preprocess ##

@preprocess.command() # update
@click.option('-i', '--idat_dir', default='./tcga_idats/', help='Idat directory if one sample sheet, alternatively can be your phenotype sample sheet.', type=click.Path(exists=False), show_default=True)
@click.option('-g', '--geo_query', default='', help='GEO study to query, do not use if already created geo sample sheet.', type=click.Path(exists=False), show_default=True)
@click.option('-o', '--output_dir', default='./preprocess_outputs/', help='Output directory for beta and phenotype data.', type=click.Path(exists=False), show_default=True)
@click.option('-ss', '--split_by_subtype', is_flag=True, help='If using formatted sample sheet csv, split by subtype and perform preprocessing. Will need to combine later.')
def plot_qc(idat_dir, geo_query, output_dir, split_by_subtype):
    os.makedirs(output_dir, exist_ok=True)
    if idat_dir.endswith('.csv') and split_by_subtype:
        pheno=pd.read_csv(idat_dir)
        for name, group in pheno.groupby('disease'):
            new_sheet = idat_dir.replace('.csv','_{}.csv'.format(name)).split('/')[-1]
            new_out_dir = '{}/{}/'.format(output_dir,name)
            os.makedirs(new_out_dir, exist_ok=True)
            group.to_csv('{}/{}'.format(new_out_dir,new_sheet))
            preprocesser = PreProcessIDAT(new_out_dir)
            preprocesser.load_idats(geo_query='')
            preprocesser.plot_original_qc(new_out_dir)
    else:
        preprocesser = PreProcessIDAT(idat_dir)
        preprocesser.load_idats(geo_query)
        preprocesser.plot_original_qc(output_dir)

@preprocess.command()
@click.option('-i', '--idat_dir', default='./tcga_idats/', help='Idat directory if one sample sheet, alternatively can be your phenotype sample sheet.', type=click.Path(exists=False), show_default=True)
@click.option('-g', '--geo_query', default='', help='GEO study to query, do not use if already created geo sample sheet.', type=click.Path(exists=False), show_default=True)
@click.option('-n', '--n_cores', default=6, help='Number cores to use for preprocessing.', show_default=True)
@click.option('-o', '--output_pkl', default='./preprocess_outputs/methyl_array.pkl', help='Output database for beta and phenotype data.', type=click.Path(exists=False), show_default=True)
@click.option('-ss', '--split_by_subtype', is_flag=True, help='If using formatted sample sheet csv, split by subtype and perform preprocessing. Will need to combine later.')
def preprocess_pipeline(idat_dir, geo_query, n_cores, output_pkl, split_by_subtype):
    os.makedirs(output_pkl[:output_pkl.rfind('/')],exist_ok=True)
    if idat_dir.endswith('.csv') and split_by_subtype:
        pheno=pd.read_csv(idat_dir)
        for name, group in pheno.groupby('disease'):
            name=name.replace(' ','')
            new_sheet = idat_dir.replace('.csv','_{}.csv'.format(name))
            #new_out_dir = '{}/{}/'.format(output_dir,name)
            os.makedirs(new_out_dir, exist_ok=True)
            group.to_csv('{}/{}'.format(new_out_dir,new_sheet))
            #os.makedirs(new_out_dir, exist_ok=True)
            preprocesser = PreProcessIDAT(new_out_dir)
            preprocesser.preprocess(geo_query='', n_cores=n_cores)
            preprocesser.output_pheno_beta()
            preprocesser.export_pickle(output_pkl,name)
            print("Please use combine_split_methylation_arrays")
    else:
        preprocesser = PreProcessIDAT(idat_dir)
        preprocesser.preprocess(geo_query, n_cores)
        preprocesser.output_pheno_beta()
        preprocesser.export_pickle(output_pkl)

@preprocess.command()
@click.option('-i', '--input_dir', default='./', help='Directory containing jpg.', type=click.Path(exists=False), show_default=True)
@click.option('-o', '--output_dir', default='./preprocess_output_images/', help='Output directory for images.', type=click.Path(exists=False), show_default=True)
def move_jpg(input_dir, output_dir):
    os.makedirs(output_dir, exist_ok=True)
    subprocess.call('mv {} {}'.format(os.path.join(input_dir,'*.jpg'),os.path.abspath(output_dir)),shell=True)


# FIXME add all below

@preprocess.command()
@click.option('-i', '--input_pkl', default='./preprocess_outputs/methyl_array.pkl', help='Input database for beta and phenotype data.', type=click.Path(exists=False), show_default=True)
@click.option('-o', '--output_pkl', default='./combined_outputs/methyl_array.pkl', help='Output database for beta and phenotype data.', type=click.Path(exists=False), show_default=True)
def combine_split_methylation_arrays(input_pkl, output_pkl):
    """If split MethylationArrays by subtype for either preprocessing or imputation, can use to recombine data for downstream step."""
    os.makedirs(output_pkl[:output_pkl.rfind('/')],exist_ok=True)
    input_dict = pickle.load(open(input_pkl,'rb'))
    tables = [table[table.find('_')+1:] for table in input_dict.keys() if '_' in table]
    diseases = np.unique(tables)
    list_methyl_arrays = []
    for disease in diseases:
        pheno_df, beta_df = extract_pheno_beta_df_from_pickle_dict(input_dict, disease)
        list_methyl_arrays.append(MethylationArray(pheno_df, beta_df))
    list_methyl_arrays = MethylationArrays(list_methyl_arrays)
    combined_methyl_array = list_methyl_arrays.combine()
    combined_methyl_array.write_pickle(output_pkl)

@preprocess.command()
@click.option('-i', '--input_pkl', default='./combined_outputs/methyl_array.pkl', help='Input database for beta and phenotype data.', type=click.Path(exists=False), show_default=True)
@click.option('-ss', '--split_by_subtype', is_flag=True, help='Imputes CpGs by subtype before combining again.')
@click.option('-m', '--method', default='KNN', help='Method of imputation.', type=click.Choice(['KNN', 'Mean', 'Zero', 'MICE', 'BiScaler', 'Soft', 'random', 'DeepCpG', 'DAPL']), show_default=True)
@click.option('-s', '--solver', default='fancyimpute', help='Imputation library.', type=click.Choice(['fancyimpute', 'impyute', 'simple']), show_default=True)
@click.option('-k', '--n_neighbors', default=5, help='Number neighbors for imputation if using KNN.', show_default=True)
@click.option('-r', '--orientation', default='Samples', help='Impute CpGs or samples.', type=click.Choice(['Samples','CpGs']), show_default=True)
@click.option('-o', '--output_pkl', default='./imputed_outputs/methyl_array.pkl', help='Output database for beta and phenotype data.', type=click.Path(exists=False), show_default=True)
def imputation_pipeline(input_pkl,split_by_subtype=True,method='knn', solver='fancyimpute', n_neighbors=5, orientation='rows', output_pkl=''): # wrap a class around this
    """Imputation of subtype or no subtype using """
    orientation_dict = {'CpGs':'columns','Samples':'rows'}
    orientation = orientation_dict[orientation]
    print("Selecting orientation for imputation not implemented yet.")
    os.makedirs(output_pkl[:output_pkl.rfind('/')],exist_ok=True)
    if method in ['DeepCpG', 'DAPL', 'EM']:
        print('Method {} coming soon...'.format(method))
    elif solver in ['impyute']:
        print('Impyute coming soon...')
    else:
        imputer = ImputerObject(solver, method, opts=dict(k=n_neighbors, orientation=orientation)).return_imputer()
        # methylationarray object impute after splitting? try to limit data usage, then export... try to limit csvs else huge data usage
    input_dict = pickle.load(open(input_pkl,'rb'))

    if split_by_subtype:

        tables = [table[table.find('_')+1:] for table in input_dict.keys() if '_' in table]
        diseases = np.unique(tables)
        if not diseases.tolist():
            methyl_array = MethylationArray(*extract_pheno_beta_df_from_pickle_dict(input_dict))
            methyl_arrays = methyl_array.split_by_subtype()
            del methyl_array
        else:
            methyl_arrays = MethylationArrays([MethylationArray(*extract_pheno_beta_df_from_pickle_dict(input_dict, disease)) for disease in diseases])

        methyl_arrays.impute(imputer)

        methyl_array = MethylationArrays.combine()

    else:
        methyl_array = MethylationArray(*extract_pheno_beta_df_from_pickle_dict(input_dict))

        methyl_array.impute(imputer)

    methyl_array.write_pickle(output_pkl)

@preprocess.command()
@click.option('-i', '--input_pkl', default='./imputed_outputs/methyl_array.pkl', help='Input database for beta and phenotype data.', type=click.Path(exists=False), show_default=True)
@click.option('-o', '--output_pkl', default='./final_preprocessed/methyl_array.pkl', help='Output database for beta and phenotype data.', type=click.Path(exists=False), show_default=True)
@click.option('-n', '--n_top_cpgs', default=300000, help='Number cpgs to include with highest variance across population.', show_default=True)
def mad_filter(input_pkl,output_pkl,n_top_cpgs=300000):
    """Filter CpGs below MAD threshold"""
    os.makedirs(output_pkl[:output_pkl.rfind('/')],exist_ok=True)
    input_dict=pickle.load(open(input_pkl,'rb'))
    methyl_array = MethylationArray(*extract_pheno_beta_df_from_pickle_dict(input_dict))

    methyl_array.mad_filter(n_top_cpgs)

    methyl_array.write_pickle(output_pkl)

@preprocess.command()
@click.option('-i', '--input_pkl', default='./final_preprocessed/methyl_array.pkl', help='Input database for beta and phenotype data.', type=click.Path(exists=False), show_default=True)
@click.option('-o', '--output_dir', default='./final_preprocessed/', help='Input database for beta and phenotype data.', type=click.Path(exists=False), show_default=True)
def pkl_to_csv(input_pkl, output_dir):
    os.makedirs(output_dir,exist_ok=True)
    input_dict=pickle.load(open(input_pkl,'rb'))
    #tables=list(map(lambda t: t,list(input_dict.keys())))
    for k in input_dict.keys():
        input_dict[k].to_csv('{}/{}.csv'.format(output_dir,k))
        #pd.read_sql('select * from {};'.format(table),conn).to_csv('{}/{}.csv'.format(output_dir,table))

@preprocess.command()
@click.option('-i', '--input_pkl', default='./final_preprocessed/methyl_array.pkl', help='Input database for beta and phenotype data.', type=click.Path(exists=False), show_default=True)
@click.option('-o', '--output_pkl', default='./backup/methyl_array.pkl', help='Output database for beta and phenotype data.', type=click.Path(exists=False), show_default=True)
def backup_pkl(input_pkl, output_pkl):
    os.makedirs(output_pkl[:output_pkl.rfind('/')],exist_ok=True)
    subprocess.call('rsync {} {}'.format(input_pkl, output_pkl),shell=True)

@preprocess.command()
@click.option('-i', '--input_pkl', default='./final_preprocessed/methyl_array.pkl', help='Input database for beta and phenotype data.', type=click.Path(exists=False), show_default=True)
def print_na_rate(input_pkl):
    df=pickle.load(open(input_pkl,'rb'))['beta']
    print('NA Rate is on average: {}%'.format(sum(sum(pd.isna(df.values)))/float(df.shape[0]*df.shape[1])*100.))

@preprocess.command()
@click.option('-i', '--input_pkl', default='./final_preprocessed/methyl_array.pkl', help='Input database for beta and phenotype data.', type=click.Path(exists=False), show_default=True)
@click.option('-is', '--input_formatted_sample_sheet', default='./tcga_idats/minfi_sheet.csv', help='Information passed through function create_sample_sheet, has Basename and disease fields.', type=click.Path(exists=False), show_default=True)
@click.option('-o', '--output_pkl', default='./modified_processed/methyl_array.pkl', help='Output database for beta and phenotype data.', type=click.Path(exists=False), show_default=True)
def modify_pheno_data(input_pkl,input_formatted_sample_sheet,output_pkl):
    """Use another spreadsheet to add more descriptive data"""
    os.makedirs(output_pkl[:output_pkl.rfind('/')],exist_ok=True)
    input_dict=pickle.load(open(input_pkl,'rb'))
    methyl_array = MethylationArray(*extract_pheno_beta_df_from_pickle_dict(input_dict))
    methyl_array.merge_preprocess_sheet(pd.read_csv(input_formatted_sample_sheet,header=0))
    methyl_array.write_pickle(output_pkl)

## Build methylation class with above features ##

## Build MethylNet (sklearn interface) and Pickle ##
# methylnet class features various dataloaders, data augmentation methods, different types variational autoencoders (load from other), with customizable architecture, etc, skorch?

# use another script for this: https://towardsdatascience.com/paper-repro-deep-neuroevolution-756871e00a66

#################

if __name__ == '__main__':
    preprocess()
