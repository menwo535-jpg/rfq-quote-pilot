import fs from 'node:fs/promises';
import path from 'node:path';
import assert from 'node:assert/strict';
import { Workbook, SpreadsheetFile } from '@oai/artifact-tool';

// Authoring utility for the Codex bundled runtime, not a standalone Python feature.
const input = path.resolve(process.argv[2] || '../output/quote-result.json');
const out = path.resolve(process.argv[3] || '../../../outputs/01a081d1-rfq');
const q = JSON.parse(await fs.readFile(input, 'utf8'));
assert(Array.isArray(q.rows) && q.rows.length > 0 && q.rows.length <= 500);
const literal = x => /^[\s]*[=+\-@]/.test(String(x)) ? "'" + String(x) : String(x);
const numeric = (x, label) => {
  assert(/^\d+(?:\.\d+)?$/.test(String(x)), `Invalid ${label}`);
  const n = Number(x);
  assert(Number.isFinite(n) && n <= 9999999999999.99, `${label} exceeds XLSX precision limit`);
  return n;
};
const wb = Workbook.create();
const s = wb.worksheets.add('Quote review');
s.showGridLines = false;
s.tabColor = '#193C56';
const start = 13, end = start + q.rows.length - 1;
s.getRange(`A1:K${end + 1}`).format.font = {name:'Arial',size:10,color:'#183047'};
s.getRange(`A1:K${end + 1}`).format.rowHeight = 22;
s.getRange(`A1:K${end + 1}`).format.verticalAlignment = 'center';
const widths = [15,20,30,12,11,19,16,23,19,40,24];
widths.forEach((w,i) => {s.getRangeByIndexes(0,i,end+1,1).format.columnWidth = w;});
s.getRange('A2').values = [['RFQ quotation draft']];
s.getRange('A2').format.font = {name:'Arial',size:16,bold:true,color:'#193C56'};
s.getRange('A3').values = [['Synthetic demonstration. Human approval is required before sending a quotation.']];
s.getRange('A3').format.font = {name:'Arial',size:10,italic:true,color:'#506579'};
s.getRange('A4:K4').format.borders = {bottom:{style:'thin',color:'#AAB9C5'}};
s.getRange('A5:A7').values = [['Draft status'],['Requested lines'],['Review required']];
s.getRange('B5').formulas = [['=IF(B7>0,"REVIEW_REQUIRED","DRAFT_FOR_APPROVAL")']];
s.getRange('B6').values = [[q.rows.length]];
s.getRange('B7').formulas = [[`=COUNTIFS(H${start}:H${end},"REVIEW")`]];
s.getRange('B5').format.font = {bold:true,color:'#183047',size:10,name:'Arial'};
s.getRange('E5:G5').values = [['Currency','Matched subtotal','Complete total']];
s.getRange('E5:G5').format = {font:{name:'Arial',size:10,bold:true,color:'#FFFFFF'},fill:'#193C56',horizontalAlignment:'center',wrapText:true,rowHeight:32};
for (const [i,currency] of ['USD','EUR','GBP','CNY'].entries()) {
  const row=6+i;
  s.getRange(`E${row}`).values = [[currency]];
  s.getRange(`F${row}`).formulas = [[`=IF(COUNTIFS(G${start}:G${end},E${row},H${start}:H${end},"MATCHED_DRAFT")=0,"",SUMIFS(I${start}:I${end},G${start}:G${end},E${row},H${start}:H${end},"MATCHED_DRAFT"))`]];
  s.getRange(`G${row}`).formulas = [[`=IF($B$7>0,"",F${row})`]];
}
s.getRange('F6:G9').setNumberFormat('#,##0.00');
s.getRange('F6:G9').format.horizontalAlignment='right';
s.getRange('I5').values=[['Complete totals remain blank while any row needs review.']];
s.getRange('I6').values=[['Correct source data and regenerate to change matching.']];
s.getRange('A10').values=[[`Source: synthetic ${q.sources?.rfq?.file || 'RFQ'} and ${q.sources?.approved_catalogue?.file || 'catalogue'}. No tax, freight, discounts or currency conversion.`]];
s.getRange('A10').format.font={name:'Arial',size:10,italic:true,color:'#506579'};
const headers=['Source row','Product code','Requested description','Quantity','Unit','Approved unit price','Currency','Match status','Line amount','Review reason','Price-list version'];
s.getRange('A12:K12').values=[headers];
const rows=q.rows.map(r=>{
  assert(['REVIEW','MATCHED_DRAFT'].includes(r.status), 'Unrecognized status');
  const matched=r.status==='MATCHED_DRAFT';
  const quantity=/^\d{1,9}(?:\.\d{1,4})?$/.test(r.quantity) ? numeric(r.quantity,'quantity') : literal(r.quantity);
  if(matched) {
    assert(quantity>0 && typeof quantity==='number');
    assert(['USD','EUR','GBP','CNY'].includes(r.currency));
    numeric(r.line_total,'line amount');
  } else {
    assert(!r.unit_price && !r.line_total,'Review rows must not carry prices');
  }
  return [literal(r.source),literal(r.code),literal(r.description),quantity,literal(r.unit),matched?numeric(r.unit_price,'price'):null,matched?r.currency:'',r.status,null,literal(r.reason),literal(r.price_version)];
});
s.getRange(`A${start}:K${end}`).values=rows;
s.getRange(`B${start}:C${end}`).setNumberFormat('@');
s.getRange(`D${start}:D${end}`).setNumberFormat('0.0000');
s.getRange(`F${start}:F${end}`).setNumberFormat('#,##0.0000');
s.getRange(`I${start}:I${end}`).setNumberFormat('#,##0.00');
s.getRange(`I${start}`).formulas=[[`=IF(H${start}="MATCHED_DRAFT",ROUND(D${start}*F${start},2),"")`]];
s.getRange(`I${start}:I${end}`).fillDown();
const table=s.tables.add(`A12:K${end}`,true,'QuoteLines');
table.style='TableStyleLight1';
table.showFilterButton=true;
s.getRange('A12:K12').format={fill:'#193C56',font:{name:'Arial',size:10,bold:true,color:'#FFFFFF'},horizontalAlignment:'center',verticalAlignment:'center',wrapText:true,rowHeight:34};
s.getRange(`A${start}:K${end}`).format.rowHeight=36;
s.getRange(`C${start}:C${end}`).format.wrapText=true;
s.getRange(`J${start}:J${end}`).format.wrapText=true;
s.getRange(`A${start}:K${end}`).conditionalFormats.addCustom(`$H${start}="REVIEW"`,{fill:'#FFF2CC'});
if(q.rows.length>12)s.freezePanes.freezeRows(12);
wb.recalculate();
assert.equal(s.getRange('B7').values[0][0],q.review_count);
const actualAmounts=s.getRange(`I${start}:I${end}`).values;
q.rows.forEach((r,i)=>{
  assert.equal(typeof s.getRange(`B${start+i}`).values[0][0],'string');
  if(/^0\d/.test(r.code))assert.equal(s.getRange(`B${start+i}`).values[0][0],r.code);
  for(const col of ['B','C','J'])assert(!s.getRange(`${col}${start+i}`).formulas[0][0],'Input text became a formula');
  if(r.status==='REVIEW')assert.equal(actualAmounts[i][0],'');
  else assert(Math.abs(actualAmounts[i][0]-Number(r.line_total))<0.000001,`Amount mismatch at row ${start+i}`);
});
for(const [i,c] of ['USD','EUR','GBP','CNY'].entries()){
  const expected=q.matched_subtotals_by_currency[c];
  const value=s.getRange(`F${6+i}`).values[0][0];
  assert.equal(value,expected===undefined?'':Number(expected));
  assert.equal(s.getRange(`G${6+i}`).values[0][0],q.review_count?'':value);
}
// Input-change check in this disposable authoring state; restore before export.
const firstMatched=q.rows.findIndex(r=>r.status==='MATCHED_DRAFT');
if(firstMatched>=0){
  const a=`D${start+firstMatched}`, original=s.getRange(a).values[0][0];
  s.getRange(a).values=[[0]];
  assert.equal(s.getRange(`I${start+firstMatched}`).values[0][0],0);
  s.getRange(a).values=[[original]];
}
wb.recalculate();
if(process.argv.includes('--check-only')) {
  console.log(JSON.stringify({checked:true,rows:q.rows.length,reviewRows:q.review_count,matchedSubtotals:q.matched_subtotals_by_currency}));
  process.exit(0);
}
const scan=await wb.inspect({kind:'match',searchTerm:'#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!',options:{useRegex:true,maxResults:30},summary:'XLSX formula error scan'});
await fs.mkdir(out,{recursive:true});
await fs.writeFile(path.join(out,'formula-scan.ndjson'),scan.ndjson);
const preview=await wb.render({sheetName:'Quote review',range:`A1:K${Math.min(end+1,26)}`,scale:1,format:'png'});
await fs.writeFile(path.join(out,'quote-preview.png'),new Uint8Array(await preview.arrayBuffer()));
await(await SpreadsheetFile.exportXlsx(wb)).save(path.join(out,'quote-draft.xlsx'));
await fs.writeFile(path.join(out,'xlsx-validation.json'),JSON.stringify({input:path.basename(input),rows:q.rows.length,reviewRows:q.review_count,matchedSubtotals:q.matched_subtotals_by_currency,completeTotalWithheld:q.review_count>0,formulaRecalculationChecked:true,nativeExcelOpened:false,notes:'Correction and matching require source regeneration; this workbook is a draft snapshot.'},null,2));
console.log(JSON.stringify({file:path.join(out,'quote-draft.xlsx'),rows:q.rows.length,reviewRows:q.review_count,formulaScan:scan.ndjson}));
